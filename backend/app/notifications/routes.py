from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.notifications import service
from app.notifications.schemas import NotificationOut

notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])


def _to_out(notification) -> NotificationOut:
    return NotificationOut.model_validate(notification)


@notifications_router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Count the current user's unread notifications (lazy reminders first)."""
    service.generate_reminders(db, current_user)
    return {"unread_count": service.unread_count(db, current_user)}


@notifications_router.get("", response_model=List[NotificationOut])
def list_notifications(
    unread_only: bool = Query(default=False),
    type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[NotificationOut]:
    """List the current user's notifications, newest first."""
    service.generate_reminders(db, current_user)
    notifications = service.list_notifications(
        db,
        current_user,
        unread_only=unread_only,
        ntype=type,
        limit=limit,
        offset=offset,
    )
    return [_to_out(n) for n in notifications]


@notifications_router.patch("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationOut:
    """Mark one of the current user's notifications as read."""
    note = service.mark_read(db, current_user, notification_id)
    return _to_out(note)


@notifications_router.post("/read-all")
def read_all(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Mark all of the current user's notifications as read."""
    return service.read_all(db, current_user)