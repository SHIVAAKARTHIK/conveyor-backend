from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, AlertStatus, User, UserRole
from app.schemas import AlertOut, AlertResolveRequest
from app.security import get_current_user
from app.ws_manager import manager

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    status_filter: AlertStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Alert)
    # Admins see every alert; everyone else only sees alerts routed to their role.
    if current_user.role != UserRole.admin:
        query = query.filter(Alert.target_role == current_user.role)
    if status_filter is not None:
        query = query.filter(Alert.status == status_filter)
    return query.order_by(Alert.created_at.desc()).all()


@router.post("/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(alert_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    if alert.status == AlertStatus.open:
        alert.status = AlertStatus.acknowledged
        db.add(alert)
        db.commit()
        db.refresh(alert)
    return alert


@router.post("/{alert_id}/resolve", response_model=AlertOut)
async def resolve_alert(
    alert_id: str,
    payload: AlertResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    alert.status = AlertStatus.resolved
    alert.resolved_by = current_user.id
    alert.resolved_at = datetime.utcnow()
    if payload.resolution_note:
        alert.message = f"{alert.message} | Resolved: {payload.resolution_note}"
    db.add(alert)
    db.commit()
    db.refresh(alert)

    await manager.broadcast("alerts", {"event": "resolved", "alert_id": alert.id})
    return alert
