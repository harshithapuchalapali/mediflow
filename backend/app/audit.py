from sqlalchemy.orm import Session

from app.models import AuditLog


def write_audit_log(
    db: Session,
    *,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Append an entry to the audit log (database-design.md §3.22).

    Flushed inside the caller's transaction so the entry is only committed
    if the triggering operation succeeds. ``user_id`` is NULL for system
    actions.
    """
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
    )
    db.add(entry)
    db.flush()
    return entry
