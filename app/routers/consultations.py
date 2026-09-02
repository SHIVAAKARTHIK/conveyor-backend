from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.firebase import send_push
from app.models import Consultation, ConsultationStatus, Patient, User, UserRole
from app.routers.patients import _get_own_patient_or_404
from app.schemas import ConsultationCreate, ConsultationOut, DoctorOut
from app.security import get_current_user, require_roles

router = APIRouter(tags=["consultations"])


def _to_out(c: Consultation) -> ConsultationOut:
    """Attaches the display-only patient/doctor names PrescriptionOut-style
    responses don't carry, so the app never needs a second round trip."""
    out = ConsultationOut.model_validate(c)
    out.patient_name = c.patient.name if c.patient else None
    out.patient_bed_no = c.patient.bed_no if c.patient else None
    out.doctor_name = c.doctor.name if c.doctor else None
    return out


@router.get("/doctors", response_model=list[DoctorOut])
def list_doctors(
    speciality: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Every logged-in role can browse the doctor directory - most useful
    for a patient picking who to request a consultation from."""
    query = db.query(User).filter(User.role == UserRole.doctor)
    if speciality:
        query = query.filter(User.department == speciality)
    return query.order_by(User.is_available.desc(), User.name).all()


@router.post("/consultations", response_model=ConsultationOut, status_code=status.HTTP_201_CREATED)
async def request_consultation(
    payload: ConsultationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.patient)),
):
    patient = _get_own_patient_or_404(db, current_user)

    doctor = db.get(User, payload.doctor_id)
    if doctor is None or doctor.role != UserRole.doctor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Doctor not found")

    consultation = Consultation(patient_id=patient.id, doctor_id=doctor.id, complaint=payload.complaint)
    db.add(consultation)
    db.commit()
    db.refresh(consultation)

    send_push(
        tokens=[doctor.fcm_token] if doctor.fcm_token else [],
        title="New consultation request",
        body=f"{patient.name} (Bed {patient.bed_no}): {payload.complaint}",
        data={"type": "consultation_request", "consultation_id": consultation.id},
    )

    return _to_out(consultation)


@router.get("/consultations", response_model=list[ConsultationOut])
def list_consultations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Role-scoped: a doctor sees requests addressed to them, a patient
    sees their own, staff/admin see everything (useful for the front desk
    to keep an eye on the queue)."""
    query = db.query(Consultation)
    if current_user.role == UserRole.doctor:
        query = query.filter(Consultation.doctor_id == current_user.id)
    elif current_user.role == UserRole.patient:
        patient = _get_own_patient_or_404(db, current_user)
        query = query.filter(Consultation.patient_id == patient.id)
    # admin/other staff: unfiltered
    consultations = query.order_by(Consultation.created_at.desc()).all()
    return [_to_out(c) for c in consultations]


@router.post("/consultations/{consultation_id}/accept", response_model=ConsultationOut)
async def accept_consultation(
    consultation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.doctor)),
):
    consultation = db.get(Consultation, consultation_id)
    if consultation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Consultation not found")
    if consultation.doctor_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your consultation request")
    if consultation.status != ConsultationStatus.requested:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Already {consultation.status.value}")

    consultation.status = ConsultationStatus.accepted
    consultation.accepted_at = datetime.utcnow()
    db.add(consultation)
    db.commit()
    db.refresh(consultation)

    patient = db.get(Patient, consultation.patient_id)
    if patient and patient.account_user and patient.account_user.fcm_token:
        send_push(
            tokens=[patient.account_user.fcm_token],
            title="Your consultation was accepted",
            body=f"Dr. {current_user.name} will prescribe shortly.",
            data={"type": "consultation_accepted", "consultation_id": consultation.id},
        )

    return _to_out(consultation)
