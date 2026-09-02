import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class UserRole(str, enum.Enum):
    admin = "admin"
    doctor = "doctor"
    nurse = "nurse"
    pharmacist = "pharmacist"
    technician = "technician"
    patient = "patient"


class PrescriptionStatus(str, enum.Enum):
    pending = "pending"
    verified = "verified"
    dispatched = "dispatched"
    delivered = "delivered"
    failed = "failed"


class DeliveryStatus(str, enum.Enum):
    preparing = "preparing"
    verifying = "verifying"
    in_transit = "in_transit"
    arrived = "arrived"
    confirmed = "confirmed"
    failed = "failed"


class AlertType(str, enum.Enum):
    medicine_mismatch = "medicine_mismatch"
    conveyor_jam = "conveyor_jam"
    motor_failure = "motor_failure"


class AlertStatus(str, enum.Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class ConsultationStatus(str, enum.Enum):
    requested = "requested"
    accepted = "accepted"
    completed = "completed"


class MotorStatus(str, enum.Enum):
    idle = "idle"
    running = "running"
    jammed = "jammed"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole))
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # For a doctor account, `department` doubles as their speciality (e.g.
    # "Cardiology") - no separate column, one less thing to keep in sync.
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Doctor's Available/Busy toggle. Defaults True so a freshly-created
    # doctor account is immediately bookable without an extra step.
    is_available: Mapped[bool] = mapped_column(default=True)
    fcm_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    patients_registered: Mapped[list["Patient"]] = relationship(
        back_populates="created_by_user", foreign_keys="Patient.created_by"
    )
    prescriptions_written: Mapped[list["Prescription"]] = relationship(back_populates="doctor")
    patient_profile: Mapped["Patient | None"] = relationship(
        back_populates="account_user", foreign_keys="Patient.user_id", uselist=False
    )
    consultations_as_doctor: Mapped[list["Consultation"]] = relationship(
        back_populates="doctor", foreign_keys="Consultation.doctor_id"
    )


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    age: Mapped[int] = mapped_column(Integer)
    gender: Mapped[str] = mapped_column(String(20))
    bed_no: Mapped[str] = mapped_column(String(20))
    qr_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_uuid)
    medical_history_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Set when the patient self-signed-up (POST /auth/signup/patient) rather
    # than being registered by a doctor/admin. Nullable so staff-registered
    # patients (no login of their own) keep working unchanged.
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    created_by_user: Mapped["User | None"] = relationship(
        back_populates="patients_registered", foreign_keys=[created_by]
    )
    account_user: Mapped["User | None"] = relationship(
        back_populates="patient_profile", foreign_keys=[user_id]
    )
    prescriptions: Mapped[list["Prescription"]] = relationship(back_populates="patient")
    consultations: Mapped[list["Consultation"]] = relationship(back_populates="patient")

    @property
    def has_account(self) -> bool:
        """True when this patient self-signed-up and can log into the app
        themselves; False when a doctor/admin registered them with no login
        of their own. Surfaced on PatientOut for the admin Patients page."""
        return self.user_id is not None


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"))
    doctor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    # Set when this prescription was written against a patient's
    # consultation request rather than typed in directly (e.g. by staff).
    consultation_id: Mapped[str | None] = mapped_column(ForeignKey("consultations.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PrescriptionStatus] = mapped_column(
        Enum(PrescriptionStatus), default=PrescriptionStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    patient: Mapped["Patient"] = relationship(back_populates="prescriptions")
    doctor: Mapped["User"] = relationship(back_populates="prescriptions_written")
    medicines: Mapped[list["Medicine"]] = relationship(
        back_populates="prescription", cascade="all, delete-orphan"
    )
    delivery: Mapped["Delivery | None"] = relationship(
        back_populates="prescription", uselist=False, cascade="all, delete-orphan"
    )


class Medicine(Base):
    __tablename__ = "medicines"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    prescription_id: Mapped[str] = mapped_column(ForeignKey("prescriptions.id"))
    name: Mapped[str] = mapped_column(String(120))
    dosage: Mapped[str] = mapped_column(String(60))
    form: Mapped[str] = mapped_column(String(30))  # tablet / capsule / syrup ...
    qty: Mapped[int] = mapped_column(Integer, default=1)
    medicine_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_uuid)

    prescription: Mapped["Prescription"] = relationship(back_populates="medicines")


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    prescription_id: Mapped[str] = mapped_column(ForeignKey("prescriptions.id"), unique=True)
    status: Mapped[DeliveryStatus] = mapped_column(Enum(DeliveryStatus), default=DeliveryStatus.preparing)
    # Snapshot of the patient's bed taken at dispatch time (by the
    # pharmacist, via verify-medicine) - NOT a live pointer to the patient
    # record. If the patient is moved after dispatch the robot still
    # completes the route it was given; see the bed_no override on
    # verify-medicine for the pharmacist correcting a stale bed before
    # dispatching.
    bed_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    prescription: Mapped["Prescription"] = relationship(back_populates="delivery")


class Consultation(Base):
    __tablename__ = "consultations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"))
    doctor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    complaint: Mapped[str] = mapped_column(Text)
    status: Mapped[ConsultationStatus] = mapped_column(Enum(ConsultationStatus), default=ConsultationStatus.requested)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="consultations")
    doctor: Mapped["User"] = relationship(back_populates="consultations_as_doctor", foreign_keys=[doctor_id])


class ConveyorStatus(Base):
    __tablename__ = "conveyor_status"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    motor_status: Mapped[MotorStatus] = mapped_column(Enum(MotorStatus), default=MotorStatus.idle)
    position: Mapped[str | None] = mapped_column(String(60), nullable=True)
    speed: Mapped[float] = mapped_column(default=0.0)
    last_jam_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    type: Mapped[AlertType] = mapped_column(Enum(AlertType))
    message: Mapped[str] = mapped_column(String(255))
    related_delivery_id: Mapped[str | None] = mapped_column(ForeignKey("deliveries.id"), nullable=True)
    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus), default=AlertStatus.open)
    target_role: Mapped[UserRole] = mapped_column(Enum(UserRole))
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
