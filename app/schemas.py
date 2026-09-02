from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models import (
    AlertStatus,
    AlertType,
    ConsultationStatus,
    DeliveryStatus,
    MotorStatus,
    PrescriptionStatus,
    UserRole,
)


# ---------- Auth ----------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    user_id: str
    name: str


class RegisterFcmTokenRequest(BaseModel):
    fcm_token: str


class PatientSignupRequest(BaseModel):
    """Public self-signup: creates a login account AND the linked Patient
    record (with bed + QR) in one step - see POST /auth/signup/patient."""

    name: str
    age: int
    gender: str
    bed_no: str
    email: EmailStr
    password: str
    phone: str | None = None


# ---------- Users ----------


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: UserRole
    phone: str | None = None
    department: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: EmailStr
    role: UserRole
    phone: str | None = None
    department: str | None = None
    is_available: bool = True
    created_at: datetime


class AvailabilityUpdate(BaseModel):
    is_available: bool


class DoctorOut(BaseModel):
    """Public-ish view of a doctor for the patient's "find a doctor" flow -
    deliberately a subset of UserOut (no email/phone)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    department: str | None = None
    is_available: bool


# ---------- Patients ----------


class PatientCreate(BaseModel):
    name: str
    age: int
    gender: str
    bed_no: str
    medical_history_notes: str | None = None


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    age: int
    gender: str
    bed_no: str
    qr_code: str
    medical_history_notes: str | None = None
    has_account: bool = False
    created_at: datetime


# ---------- Medicines / Prescriptions ----------


class MedicineCreate(BaseModel):
    name: str
    dosage: str
    form: str
    qty: int = 1


class MedicineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    dosage: str
    form: str
    qty: int
    medicine_code: str


class PrescriptionCreate(BaseModel):
    patient_id: str
    notes: str | None = None
    medicines: list[MedicineCreate]
    consultation_id: str | None = None


class PrescriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    doctor_id: str
    consultation_id: str | None = None
    notes: str | None = None
    status: PrescriptionStatus
    created_at: datetime
    medicines: list[MedicineOut] = []


# ---------- Deliveries ----------


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    prescription_id: str
    status: DeliveryStatus
    bed_no: str | None = None
    verified_by: str | None = None
    confirmed_by: str | None = None
    prepared_at: datetime | None = None
    verified_at: datetime | None = None
    dispatched_at: datetime | None = None
    arrived_at: datetime | None = None
    confirmed_at: datetime | None = None
    created_at: datetime
    # Enriched for the pharmacist/nurse screens so neither has to type or
    # look up a bed number - see _to_out() in routers/deliveries.py.
    patient_name: str | None = None
    patient_bed_no: str | None = None
    medicines: list[MedicineOut] = []


class MedicineVerifyRequest(BaseModel):
    """Pharmacist scans the medicine QR label on the box they just packed.
    The scan itself is the verification step - no separate patient QR check
    here, that happens at the bedside via PatientVerifyRequest instead."""

    delivery_id: str
    scanned_medicine_code: str
    # Lets the pharmacist correct a stale bed (patient moved) before
    # dispatch; defaults to the patient's current bed_no when omitted.
    bed_no: str | None = None


class PatientVerifyRequest(BaseModel):
    """Bedside re-scan of the patient wristband QR to confirm delivery."""

    delivery_id: str
    scanned_patient_qr: str


# ---------- Conveyor ----------


class ConveyorStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    motor_status: MotorStatus
    position: str | None = None
    speed: float
    last_jam_at: datetime | None = None
    updated_at: datetime


class ConveyorSimulateRequest(BaseModel):
    motor_status: MotorStatus
    position: str | None = None
    speed: float | None = None


class ConveyorJobOut(BaseModel):
    """The only thing the conveyor station needs to run a delivery: which
    job it is, and which bed to push the box into. Returned by
    GET /conveyor/next-job; the endpoint returns 204 when nothing is
    waiting, so the firmware can poll it cheaply."""

    delivery_id: str
    bed_no: str
    patient_name: str


# ---------- Alerts ----------


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: AlertType
    message: str
    related_delivery_id: str | None = None
    status: AlertStatus
    target_role: UserRole
    resolved_by: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class AlertResolveRequest(BaseModel):
    resolution_note: str | None = None


# ---------- Consultations ----------


class ConsultationCreate(BaseModel):
    doctor_id: str
    complaint: str


class ConsultationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    doctor_id: str
    complaint: str
    status: ConsultationStatus
    created_at: datetime
    accepted_at: datetime | None = None
    # Denormalized display fields so the app doesn't need a second round
    # trip just to show "who" on either side of the request.
    patient_name: str | None = None
    patient_bed_no: str | None = None
    doctor_name: str | None = None
