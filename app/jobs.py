"""Work that runs outside a normal page request: the compliance digest.

The Reports page calls run_digest() directly ("Generate digest now"). On AWS, an
EventBridge schedule invokes the Lambda with {"cyanguard_task": "digest"}, which
lambda_handler routes to run_scheduled_task().
"""
from datetime import datetime, timezone

from app import config
from app.services.app_settings import load_settings
from app.services.cases import ensure_case
from app.services.notify import EmailSender, send_notification
from app.services.reports import build_digest
from app.services.storage import DIGESTS, NOTIFICATIONS, REVIEWS, SETTINGS, Database

SCHEDULER = {"id": "scheduler", "name": "Scheduled digest"}


def reviews_with_cases(db: Database) -> list[dict]:
    settings = load_settings(db.collection(SETTINGS))
    reviews = db.collection(REVIEWS).list()
    for review in reviews:
        ensure_case(review, settings)
    return reviews


def run_digest(
    db: Database,
    email: EmailSender | None,
    *,
    now: datetime,
    days: int,
    trigger: str,
    created_by: dict,
    app_url: str = "",
) -> dict:
    """Build a digest, save it, and send it (outbox always; email if turned on)."""
    settings = load_settings(db.collection(SETTINGS))
    digest = build_digest(
        reviews_with_cases(db), now=now, days=days, trigger=trigger, created_by=created_by, app_url=app_url,
    )
    note = send_notification(
        db.collection(NOTIFICATIONS),
        email if settings.email_notifications else None,
        event="digest",
        subject=digest["subject"],
        body=digest["body"],
        now=now,
    )
    digest["delivery"] = note["delivery"]
    return db.collection(DIGESTS).put(digest)


def run_scheduled_task(task: str) -> dict:
    """Entry point for EventBridge-triggered Lambda invocations."""
    from app.deps import get_db, get_email_sender  # here to avoid a circular import

    if task != "digest":
        return {"ok": False, "error": f"Unknown task {task!r}"}
    db = get_db()
    digest = run_digest(
        db,
        get_email_sender(),
        now=datetime.now(timezone.utc),
        days=load_settings(db.collection(SETTINGS)).digest_days,
        trigger="scheduled",
        created_by=SCHEDULER,
        app_url=config.APP_URL,
    )
    return {"ok": True, "digest_id": digest["id"], "delivery": digest["delivery"]["status"]}
