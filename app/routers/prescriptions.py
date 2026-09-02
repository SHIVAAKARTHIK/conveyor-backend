from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.firebase import send_push
from app.models import Consultation, ConsultationStatus, Delivery, Medicine, Patient, Prescription, User, UserRole
from app.qr import qr_code_png_base64
from app.schemas import PrescriptionCreate, PrescriptionOut
from app.security import get_current_user, require_roles
from app.ws_manager import manager

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])


@router.get("", response_model=list[PrescriptionOut])
def list_prescriptions(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return db.query(Prescription).order_by(Prescription.created_at.desc()).all()


@router.get("/{prescription_id}", response_model=PrescriptionOut)
def get_prescription(
    prescription_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
):
    prescription = db.get(Prescription, prescription_id)
    if prescription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prescription not found")
    return prescription


@router.get("/medicines/{medicine_id}/qr")
def get_medicine_qr(medicine_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """QR/barcode image for a single prescribed medicine - this is what the
    nurse scans (alongside the patient's QR) during medicine verification."""
    medicine = db.get(Medicine, medicine_id)
    if medicine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine not found")
    return {"medicine_code": medicine.medicine_code, "qr_image_base64": qr_code_png_base64(medicine.medicine_code)}


@router.post("", response_model=PrescriptionOut, status_code=status.HTTP_201_CREATED)
async def create_prescription(
    payload: PrescriptionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.doctor, UserRole.admin)),
):
    patient = db.get(Patient, payload.patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    if not payload.medicines:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="At least one medicine is required")

    consultation = None
    if payload.consultation_id:
        consultation = db.get(Consultation, payload.consultation_id)
        if consultation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consultation not found")
        if consultation.doctor_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your consultation request")
        if consultation.patient_id != patient.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Consultation is for a different patient")

    prescription = Prescription(
        patient_id=patient.id,
        doctor_id=current_user.id,
        consultation_id=consultation.id if consultation else None,
        notes=payload.notes,
    )
    prescription.medicines = [
        Medicine(name=m.name, dosage=m.dosage, form=m.form, qty=m.qty) for m in payload.medicines
    ]
    db.add(prescription)
    db.flush()  # assign prescription.id before creating the delivery row

    delivery = Delivery(prescription_id=prescription.id)
    db.add(delivery)

    if consultation is not None:
        consultation.status = ConsultationStatus.completed
        db.add(consultation)

    db.commit()
    db.refresh(prescription)

    # Notify nurses & pharmacists: new prescription needs to be prepared.
    staff = db.query(User).filter(User.role.in_([UserRole.nurse, UserRole.pharmacist])).all()
    send_push(
        tokens=[u.fcm_token for u in staff],
        title="New prescription to prepare",
        body=f"{patient.name} (Bed {patient.bed_no}) has a new prescription.",
        data={"type": "new_prescription", "prescription_id": prescription.id, "patient_id": patient.id},
    )
    await manager.broadcast(
        "prescriptions",
        {"event": "created", "prescription_id": prescription.id, "patient_id": patient.id},
    )

    return prescription
