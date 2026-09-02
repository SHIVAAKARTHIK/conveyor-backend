from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.firebase import send_push
from app.models import (
    Alert,
    AlertType,
    Delivery,
    DeliveryStatus,
    Prescription,
    PrescriptionStatus,
    User,
    UserRole,
)
from app.routers.patients import _get_own_patient_or_404
from app.schemas import DeliveryOut, MedicineVerifyRequest, PatientVerifyRequest
from app.security import get_current_user, require_roles
from app.ws_manager import manager

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


def _get_delivery_or_404(db: Session, delivery_id: str) -> Delivery:
    delivery = db.get(Delivery, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    return delivery


def _to_out(delivery: Delivery) -> DeliveryOut:
    """Enriches a Delivery with the patient's name/bed and the medicine
    list, so the pharmacist and nurse screens can show "Deliver to: <name> -
    Bed <no>" and what's being packed, without a second round trip or the
    pharmacist typing anything themselves."""
    out = DeliveryOut.model_validate(delivery)
    prescription = delivery.prescription
    if prescription is not None:
        out.medicines = list(prescription.medicines)
        patient = prescription.patient
        if patient is not None:
            out.patient_name = patient.name
            out.patient_bed_no = patient.bed_no
    return out


@router.get("", response_model=list[DeliveryOut])
def list_deliveries(
    status_filter: DeliveryStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Delivery)
    if status_filter is not None:
        query = query.filter(Delivery.status == status_filter)
    # A patient only ever sees their own deliveries - everyone else (staff)
    # sees the ward-wide queue, same as before.
    if current_user.role == UserRole.patient:
        patient = _get_own_patient_or_404(db, current_user)
        query = query.join(Prescription).filter(Prescription.patient_id == patient.id)
    deliveries = query.order_by(Delivery.created_at.desc()).all()
    return [_to_out(d) for d in deliveries]


@router.get("/{delivery_id}", response_model=DeliveryOut)
def get_delivery(delivery_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    delivery = _get_delivery_or_404(db, delivery_id)
    if current_user.role == UserRole.patient:
        patient = _get_own_patient_or_404(db, current_user)
        if delivery.prescription is None or delivery.prescription.patient_id != patient.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    return _to_out(delivery)


@router.post("/{delivery_id}/dispatch", response_model=DeliveryOut)
async def dispatch_delivery(
    delivery_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.technician, UserRole.admin)),
):
    """Start a delivery with **no scan and no payload** - the conveyor station
    calls this the moment its physical button is pressed.

    This is the whole dispatch step in the minimal build: the operator loads
    the box and presses the button, and that press *is* the dispatch. There is
    deliberately no verification here (see docs/phase-3-conveyor-plan.md); the
    scan-based `verify-medicine` endpoint still exists for anyone who wants
    that gate back.

    Snapshots the patient's bed number onto the delivery so the station routes
    to where the patient was when the run started, even if the record changes
    mid-run.
    """
    delivery = _get_delivery_or_404(db, delivery_id)
    if delivery.status != DeliveryStatus.preparing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Delivery is '{delivery.status.value}', expected 'preparing'",
        )

    prescription = db.get(Prescription, delivery.prescription_id)
    patient = prescription.patient

    delivery.bed_no = patient.bed_no
    delivery.status = DeliveryStatus.in_transit
    delivery.verified_by = current_user.id
    now = datetime.utcnow()
    # All three set together so the admin timeline UI still renders a
    # sensible sequence even though there is no separate prepare/verify step.
    delivery.prepared_at = now
    delivery.verified_at = now
    delivery.dispatched_at = now
    db.add(delivery)

    prescription.status = PrescriptionStatus.dispatched
    db.add(prescription)
    db.commit()
    db.refresh(delivery)

    await manager.broadcast("conveyor", {"event": "dispatched", "delivery_id": delivery.id})
    return _to_out(delivery)


@router.post("/{delivery_id}/verify-medicine", response_model=DeliveryOut)
async def verify_medicine(
    delivery_id: str,
    payload: MedicineVerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.pharmacist, UserRole.admin)),
):
    """The pharmacist's single dispatch action: scan the medicine QR label
    stuck on the box they just packed. The scan *is* the verification - there
    is no separate "mark prepared" tap and no patient QR here (that check
    happens at the bedside, via /confirm). Mirrors the report's 'Medication
    Verification -> Is medicine Correct?' gate: mismatch raises a Medical
    Failure Alert and the robot is never dispatched."""
    delivery = _get_delivery_or_404(db, delivery_id)
    if delivery.id != payload.delivery_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="delivery_id mismatch")
    if delivery.status != DeliveryStatus.preparing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Delivery is '{delivery.status.value}', expected 'preparing'")

    prescription = db.get(Prescription, delivery.prescription_id)
    patient = prescription.patient
    medicine_codes = {m.medicine_code for m in prescription.medicines}

    if payload.scanned_medicine_code not in medicine_codes:
        delivery.status = DeliveryStatus.failed
        db.add(delivery)

        alert = Alert(
            type=AlertType.medicine_mismatch,
            message=(
                f"Wrong medicine QR scanned for delivery {delivery.id} "
                f"(patient {patient.name}, bed {patient.bed_no})."
            ),
            related_delivery_id=delivery.id,
            target_role=UserRole.doctor,
        )
        db.add(alert)
        prescription.status = PrescriptionStatus.failed
        db.add(prescription)
        db.commit()
        db.refresh(delivery)

        doctors = db.query(User).filter(User.role == UserRole.doctor).all()
        send_push(
            tokens=[u.fcm_token for u in doctors],
            title="Medicine mismatch alert",
            body=alert.message,
            data={"type": "medicine_mismatch", "alert_id": alert.id, "delivery_id": delivery.id},
        )
        await manager.broadcast("alerts", {"event": "created", "alert_type": "medicine_mismatch", "alert_id": alert.id})
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Scanned medicine QR did not match this prescription; alert raised")

    # Snapshot the bed now - if the patient gets moved after this point the
    # robot still completes the route it was given (edge case: patient
    # moved after dispatch). bed_no lets the pharmacist correct a stale
    # bed before dispatching instead of typing one from scratch.
    delivery.bed_no = payload.bed_no or patient.bed_no
    delivery.status = DeliveryStatus.in_transit
    delivery.verified_by = current_user.id
    now = datetime.utcnow()
    # Both set here (rather than via a separate mark-prepared step) so the
    # admin dashboard's existing prepared/verified timeline UI still renders.
    delivery.prepared_at = now
    delivery.verified_at = now
    delivery.dispatched_at = now
    db.add(delivery)

    prescription.status = PrescriptionStatus.dispatched
    db.add(prescription)
    db.commit()
    db.refresh(delivery)

    await manager.broadcast("conveyor", {"event": "dispatched", "delivery_id": delivery.id})
    return _to_out(delivery)


@router.post("/{delivery_id}/mark-arrived", response_model=DeliveryOut)
async def mark_arrived(
    delivery_id: str,
    db: Session = Depends(get_db),
    _staff: User = Depends(require_roles(UserRole.nurse, UserRole.technician, UserRole.admin)),
):
    """Called once the conveyor (real ESP32 later, simulator for now, or a
    nurse's manual fallback until the robot exists) reports the package has
    physically reached the ward/bedside."""
    delivery = _get_delivery_or_404(db, delivery_id)
    if delivery.status != DeliveryStatus.in_transit:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Delivery is '{delivery.status.value}', expected 'in_transit'")

    delivery.status = DeliveryStatus.arrived
    delivery.arrived_at = datetime.utcnow()
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    await manager.broadcast("conveyor", {"event": "arrived", "delivery_id": delivery.id})
    return _to_out(delivery)


@router.post("/{delivery_id}/confirm", response_model=DeliveryOut)
async def confirm_delivery(
    delivery_id: str,
    payload: PatientVerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.nurse, UserRole.admin)),
):
    """Final bedside QR re-scan confirming the right patient received the
    right medicine ('Patient Verification' + 'Delivery Confirmation' in the
    report's block diagram)."""
    delivery = _get_delivery_or_404(db, delivery_id)
    if delivery.status != DeliveryStatus.arrived:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Delivery is '{delivery.status.value}', expected 'arrived'")

    prescription = db.get(Prescription, delivery.prescription_id)
    patient = prescription.patient
    if payload.scanned_patient_qr != patient.qr_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Scanned patient QR does not match this delivery's patient")

    delivery.status = DeliveryStatus.confirmed
    delivery.confirmed_by = current_user.id
    delivery.confirmed_at = datetime.utcnow()
    db.add(delivery)

    prescription.status = PrescriptionStatus.delivered
    db.add(prescription)
    db.commit()
    db.refresh(delivery)

    await manager.broadcast("conveyor", {"event": "confirmed", "delivery_id": delivery.id})
    return _to_out(delivery)
