"""Case notifications: always saved to the in-app outbox, optionally emailed via Amazon SNS.

The outbox is the audit record of every alert CyanGuard raised, whether or not it was
emailed. A failed email never breaks the request that triggered it; the failure is
recorded on the outbox entry instead.
"""
import uuid
from datetime import datetime
from typing import Protocol

from app.services.storage import Storage

MAX_SUBJECT = 100  # SNS rejects email subjects longer than this


class EmailSender(Protocol):
    def send(self, subject: str, body: str) -> str:
        """Send the email and return a delivery ID. Raise on failure."""
        ...


class SnsEmailSender:
    """Publishes to an SNS topic; everyone subscribed to the topic by email gets it."""

    def __init__(self, topic_arn: str, region: str):
        import boto3  # imported lazily so local mode doesn't need boto3

        self.client = boto3.client("sns", region_name=region)
        self.topic_arn = topic_arn

    def send(self, subject: str, body: str) -> str:
        response = self.client.publish(TopicArn=self.topic_arn, Subject=subject, Message=body)
        return response["MessageId"]


def build_message(event: str, review: dict, case_url: str, note: str = "") -> tuple[str, str]:
    """Subject and plain-text body for a case notification."""
    case = review["case"]
    status = review["status"].replace("_", " ")
    headline = {
        "case_opened": f"New {case['priority']}-priority case: {status}",
        "case_escalated": f"Case escalated: {status}",
    }[event]
    subject = f"[CyanGuard] {headline}"[:MAX_SUBJECT]

    flags = review["flags"]
    lines = [
        headline,
        "",
        f"Safety score: {review['score']}/100   Flags: {len(flags)}",
        f"Submitted by: {review.get('submitted_by', {}).get('name', 'Unknown')}",
        f"Resolve by:   {case['due_at']} (UTC)",
    ]
    if note:
        lines += ["", f"Escalation note: {note}"]
    lines += ["", "AI output:", review["text"][:600] + ("…" if len(review["text"]) > 600 else "")]
    if flags:
        lines += ["", "Flags:"]
        lines += [f"  - [{f['severity'].upper()}] {f['title']} ({f['citation']})" for f in flags[:8]]
        if len(flags) > 8:
            lines.append(f"  … and {len(flags) - 8} more")
    lines += ["", f"Open the case: {case_url}"]
    return subject, "\n".join(lines)


def notify(
    outbox: Storage,
    sender: EmailSender | None,
    *,
    event: str,
    review: dict,
    case_url: str,
    now: datetime,
    note: str = "",
) -> dict:
    """Record a case notification in the outbox and email it if a sender is given."""
    subject, body = build_message(event, review, case_url, note)
    return send_notification(
        outbox, sender, event=event, subject=subject, body=body, now=now,
        review_id=review["id"], status=review["status"],
    )


def send_notification(
    outbox: Storage,
    sender: EmailSender | None,
    *,
    event: str,
    subject: str,
    body: str,
    now: datetime,
    review_id: str | None = None,
    status: str | None = None,
) -> dict:
    """Save any notification to the outbox, and email it if a sender is given."""
    entry = {
        "id": str(uuid.uuid4()),
        # Milliseconds so alerts raised in the same second still sort newest-first.
        "created_at": now.isoformat(timespec="milliseconds"),
        "event": event,
        "review_id": review_id,
        "status": status,
        "subject": subject[:MAX_SUBJECT],
        "body": body,
        "channel": "email" if sender else "outbox",
    }
    if sender is None:
        entry["delivery"] = {"status": "outbox", "detail": "Email alerts are off; saved to the outbox only."}
    else:
        try:
            entry["delivery"] = {"status": "sent", "detail": f"SNS message {sender.send(subject, body)}"}
        except Exception as exc:  # noqa: BLE001 - any send failure is recorded, never raised
            entry["delivery"] = {"status": "failed", "detail": f"{type(exc).__name__}: {exc}"[:300]}
    return outbox.put(entry)
