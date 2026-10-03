"""Compliance cases: the human-review workflow for flagged AI outputs.

Every FAIL / NEEDS_REVIEW review gets a case, stored on the review itself under
"case". Compliance officers move it through these states:

    open ──assign──► in_review ──approve / reject──► approved / rejected
      │                  │
      └────escalate──────┴──► escalated ──approve / reject (admin only)──► resolved

Resolved cases can be reopened by an admin. Every change is appended to the case
history, which is never edited, so the case keeps a full audit trail.
"""
from datetime import datetime, timedelta

from app.services.app_settings import AppSettings
from app.services.auth import role_at_least

STATES = ("open", "in_review", "escalated", "approved", "rejected")
RESOLVED = ("approved", "rejected")
SYSTEM = {"id": "system", "name": "CyanGuard"}

# action -> (states it can start from, state it moves to, note required)
ACTIONS = {
    "assign": (("open", "in_review", "escalated"), None, False),  # None: see apply_action
    "approve": (("open", "in_review", "escalated"), "approved", False),
    "reject": (("open", "in_review", "escalated"), "rejected", True),
    "escalate": (("open", "in_review"), "escalated", True),
    "reopen": (RESOLVED, "open", True),
}


class CaseError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def new_case(review: dict, settings: AppSettings, now: datetime) -> dict | None:
    """The case for a freshly checked review, or None if it passed."""
    if review["status"] == "PASS":
        return None
    priority = "high" if review["status"] == "FAIL" else "normal"
    hours = settings.sla_hours_high if priority == "high" else settings.sla_hours_normal
    return {
        "state": "open",
        "priority": priority,
        "opened_at": _iso(now),
        "due_at": _iso(now + timedelta(hours=hours)),
        "assignee": None,
        "resolved_at": None,
        "history": [{
            "at": _iso(now),
            "by": SYSTEM,
            "action": "open",
            "from": None,
            "to": "open",
            "note": f"{review['status'].replace('_', ' ').title()} result with {len(review['flags'])} flag(s).",
        }],
    }


def ensure_case(review: dict, settings: AppSettings) -> dict | None:
    """Reviews saved before cases existed get one, dated from when they were checked."""
    if "case" not in review:
        review["case"] = new_case(review, settings, datetime.fromisoformat(review["created_at"]))
    return review["case"]


def apply_action(
    review: dict,
    action: str,
    *,
    actor: dict,
    now: datetime,
    note: str = "",
    assignee: dict | None = None,
) -> dict:
    """Apply a workflow action to the review's case (in place) and return the case."""
    case = review.get("case")
    if case is None:
        raise CaseError("This review passed, so it has no case")
    if action not in ACTIONS:
        raise CaseError(f"Unknown action {action!r}")

    allowed_from, to_state, note_required = ACTIONS[action]
    state = case["state"]
    if state not in allowed_from:
        raise CaseError(f"Can't {action} a case that is {state.replace('_', ' ')}", 409)
    if note_required and not note.strip():
        raise CaseError(f"A note is required to {action} a case")
    if state == "escalated" and action in ("approve", "reject") and not role_at_least(actor["role"], "admin"):
        raise CaseError("Only an admin can resolve an escalated case", 403)
    if action == "reopen" and not role_at_least(actor["role"], "admin"):
        raise CaseError("Only an admin can reopen a case", 403)

    if action == "assign":
        target = assignee or actor
        if not role_at_least(target["role"], "compliance"):
            raise CaseError("Cases can only be assigned to compliance officers or admins")
        case["assignee"] = {"id": target["id"], "name": target["name"]}
        to_state = "escalated" if state == "escalated" else "in_review"

    case["state"] = to_state
    case["resolved_at"] = _iso(now) if to_state in RESOLVED else None
    case["history"].append({
        "at": _iso(now),
        "by": {"id": actor["id"], "name": actor["name"]},
        "action": action,
        "from": state,
        "to": to_state,
        "note": note.strip(),
        **({"assignee": case["assignee"]} if action == "assign" else {}),
    })
    return case
