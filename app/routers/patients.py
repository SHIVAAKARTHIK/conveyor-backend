from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Delivery, DeliveryStatus, Patient, Prescription, User, UserRole
from app.qr import qr_code_png_base64
from app.schemas import PatientBedAssign, PatientCreate, PatientOut
from app.security import get_current_user, require_roles

router = APIRouter(prefix="/patients", tags=["patients"])

# Every endpoint below except /me and /me/qr is hospital-staff-only: once
# patients are real logins (see POST /auth/signup/patient), a plain
# get_current_user guard would let one patient browse every other patient's
# record. Staff roles keep full access; a patient only ever sees themself.
_STAFF_ROLES = (UserRole.doctor, UserRole.nurse, UserRole.pharmacist, UserRole.technician, UserRole.admin)


def _get_own_patient_or_404(db: Session, current_user: User) -> Patient:
    patient = db.query(Patient).filter(Patient.user_id == current_user.id).first()
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No patient profile linked to this account")
    return patient


@router.get("/me", response_model=PatientOut)
def get_my_patient(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.patient)),
):
    return _get_own_patient_or_404(db, current_user)


@router.get("/me/qr")
def get_my_patient_qr(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.patient)),
):
    patient = _get_own_patient_or_404(db, current_user)
    return {"qr_code": patient.qr_code, "qr_image_base64": qr_code_png_base64(patient.qr_code)}


@router.get("", response_model=list[PatientOut])
def list_patients(db: Session = Depends(get_db), _user: User = Depends(require_roles(*_STAFF_ROLES))):
    return db.query(Patient).order_by(Patient.created_at.desc()).all()


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: str, db: Session = Depends(get_db), _user: User = Depends(require_roles(*_STAFF_ROLES))):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return patient


@router.get("/{patient_id}/qr")
def get_patient_qr(patient_id: str, db: Session = Depends(get_db), _user: User = Depends(require_roles(*_STAFF_ROLES))):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return {"qr_code": patient.qr_code, "qr_image_base64": qr_code_png_base64(patient.qr_code)}


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.doctor, UserRole.admin)),
):
    patient = Patient(
        name=payload.name,
        age=payload.age,
        gender=payload.gender,
        bed_no=payload.bed_no,
        medical_history_notes=payload.medical_history_notes,
        created_by=current_user.id,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.patch("/{patient_id}/bed", response_model=PatientOut)
def assign_bed(
    patient_id: str,
    payload: PatientBedAssign,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.nurse, UserRole.admin)),
):
    """A nurse puts the patient in Bed 1 or Bed 2 (or moves them). The bed on the
    record is what routes a delivery, so it cannot change while a box for that
    patient is already on the belt."""
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    on_the_belt = (
        db.query(Delivery)
        .join(Prescription, Prescription.id == Delivery.prescription_id)
        .filter(Prescription.patient_id == patient.id, Delivery.status == DeliveryStatus.in_transit)
        .first()
    )
    if on_the_belt is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A delivery for this patient is on the belt right now - wait until it arrives",
        )
    patient.bed_no = payload.bed_no
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient
