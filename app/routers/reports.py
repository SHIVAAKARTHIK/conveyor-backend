from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, AlertStatus, Delivery, DeliveryStatus, User, UserRole
from app.security import require_roles

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/summary")
def summary(
    days: int = 14,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.admin)),
):
    since = datetime.utcnow() - timedelta(days=days)

    deliveries_per_day = (
        db.query(func.date(Delivery.created_at).label("day"), func.count(Delivery.id))
        .filter(Delivery.created_at >= since)
        .group_by(func.date(Delivery.created_at))
        .order_by(func.date(Delivery.created_at))
        .all()
    )

    confirmed = (
        db.query(Delivery)
        .filter(Delivery.status == DeliveryStatus.confirmed, Delivery.dispatched_at.isnot(None))
        .filter(Delivery.created_at >= since)
        .all()
    )
    avg_delivery_seconds = None
    if confirmed:
        total_seconds = sum(
            (d.confirmed_at - d.dispatched_at).total_seconds()
            for d in confirmed
            if d.confirmed_at and d.dispatched_at
        )
        avg_delivery_seconds = total_seconds / len(confirmed)

    alert_counts = (
        db.query(Alert.type, func.count(Alert.id))
        .filter(Alert.created_at >= since)
        .group_by(Alert.type)
        .all()
    )

    open_alerts = db.query(Alert).filter(Alert.status != AlertStatus.resolved).count()

    return {
        "deliveries_per_day": [{"day": str(day), "count": count} for day, count in deliveries_per_day],
        "avg_delivery_seconds": avg_delivery_seconds,
        "alert_counts_by_type": {t.value: c for t, c in alert_counts},
        "open_alerts": open_alerts,
        "total_deliveries": db.query(Delivery).filter(Delivery.created_at >= since).count(),
    }
