from datetime import datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.firebase import send_push
from app.models import (
    Alert,
    AlertType,
    ConveyorStatus,
    Delivery,
    DeliveryStatus,
    MotorStatus,
    User,
    UserRole,
)
from app.schemas import ConveyorJobOut, ConveyorSimulateRequest, ConveyorStatusOut
from app.security import get_current_user, require_roles
from app.ws_manager import manager

router = APIRouter(prefix="/conveyor", tags=["conveyor"])


def _get_or_create_status(db: Session) -> ConveyorStatus:
    status_row = db.query(ConveyorStatus).first()
    if status_row is None:
        status_row = ConveyorStatus()
        db.add(status_row)
        db.commit()
        db.refresh(status_row)
    return status_row


@router.get("/status", response_model=ConveyorStatusOut)
def get_status(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return _get_or_create_status(db)


@router.get("/next-job", response_model=ConveyorJobOut)
def next_job(
    db: Session = Depends(get_db),
    _staff: User = Depends(require_roles(UserRole.technician, UserRole.admin)),
):
    """The conveyor station polls this every few seconds while idle.

    Returns the **oldest delivery still `preparing`** - i.e. a prescription
    has been written but nobody has loaded and dispatched it yet. FIFO, so
    with several jobs queued the one waiting longest goes first and there is
    never ambiguity about which box the operator should load next.

    Returns **204 No Content** when there is nothing waiting, which keeps the
    polling loop cheap and lets the firmware treat "no body" as "stay idle".
    """
    delivery = (
        db.query(Delivery)
        .filter(Delivery.status == DeliveryStatus.preparing)
        .order_by(Delivery.created_at)
        .first()
    )
    if delivery is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    prescription = delivery.prescription
    patient = prescription.patient if prescription else None
    if patient is None:
        # Orphaned delivery - skip it rather than handing the station a job
        # it cannot route anywhere.
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return ConveyorJobOut(
        delivery_id=delivery.id,
        bed_no=patient.bed_no,
        patient_name=patient.name,
    )


@router.post("/simulate", response_model=ConveyorStatusOut)
async def simulate(
    payload: ConveyorSimulateRequest,
    db: Session = Depends(get_db),
    _staff: User = Depends(require_roles(UserRole.technician, UserRole.admin)),
):
    """Debug/dev endpoint the Admin website's conveyor-simulator panel calls
    to fake IR-sensor/motor state without real hardware. The future ESP32
    firmware will call this exact same shape of endpoint (swap the auth for
    a device API key) so no app/website changes are needed at hardware
    integration time."""
    status_row = _get_or_create_status(db)
    status_row.motor_status = payload.motor_status
    if payload.position is not None:
        status_row.position = payload.position
    if payload.speed is not None:
        status_row.speed = payload.speed
    if payload.motor_status in (MotorStatus.jammed, MotorStatus.failed):
        status_row.last_jam_at = datetime.utcnow()
    db.add(status_row)

    alert = None
    if payload.motor_status in (MotorStatus.jammed, MotorStatus.failed):
        alert_type = AlertType.conveyor_jam if payload.motor_status == MotorStatus.jammed else AlertType.motor_failure
        alert = Alert(
            type=alert_type,
            message=f"Conveyor reported '{payload.motor_status.value}'.",
            target_role=UserRole.technician,
        )
        db.add(alert)

    db.commit()
    db.refresh(status_row)

    await manager.broadcast("conveyor", {"event": "status_update", "motor_status": status_row.motor_status.value})

    if alert is not None:
        technicians = db.query(User).filter(User.role == UserRole.technician).all()
        send_push(
            tokens=[u.fcm_token for u in technicians],
            title="Conveyor failure alert",
            body=alert.message,
            data={"type": alert.type.value, "alert_id": alert.id},
        )
        await manager.broadcast("alerts", {"event": "created", "alert_type": alert.type.value, "alert_id": alert.id})

    return status_row
