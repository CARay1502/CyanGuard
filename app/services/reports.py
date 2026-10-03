"""Report numbers, the compliance digest, and CSV export.

Everything is computed from the reviews (and their cases) on demand, so the Reports
page, the digest, and the CSV always agree.
"""
import csv
import io
import uuid
from datetime import datetime, timedelta

from app.services.cases import RESOLVED

STATUSES = ("PASS", "NEEDS_REVIEW", "FAIL")


def _when(review: dict) -> datetime:
    return datetime.fromisoformat(review["created_at"])


def in_window(reviews: list[dict], now: datetime, days: int) -> list[dict]:
    start = now - timedelta(days=days)
    return [r for r in reviews if _when(r) >= start]


def summarize(reviews: list[dict], *, now: datetime, days: int, tz_offset_minutes: int = 0) -> dict:
    """Numbers for the Reports page.

    `reviews` must already have cases attached (see cases.ensure_case). Counts cover the
    last `days` days; the case snapshot (open, overdue) is current, whatever the window.
    `tz_offset_minutes` is the browser's Date.getTimezoneOffset(), so days are bucketed
    in the viewer's local time.
    """
    start = now - timedelta(days=days)
    window = in_window(reviews, now, days)
    tz_offset = timedelta(minutes=tz_offset_minutes)
    today = (now - tz_offset).date()

    # Daily result counts, oldest day first, including empty days.
    daily = {today - timedelta(days=i): dict.fromkeys(STATUSES, 0) for i in range(days)}
    for r in window:
        day = (_when(r) - tz_offset).date()
        if day in daily:
            daily[day][r["status"]] += 1

    # Most-triggered rules, counted once per review.
    rules: dict[str, dict] = {}
    for r in window:
        for flag in {f["rule_id"]: f for f in r["flags"]}.values():
            entry = rules.setdefault(flag["rule_id"], {
                "rule_id": flag["rule_id"], "title": flag["title"], "severity": flag["severity"], "count": 0,
            })
            entry["count"] += 1

    # Cases: a live snapshot plus how fast cases resolved in this window.
    cases = [r["case"] for r in reviews if r.get("case")]
    active = [c for c in cases if c["state"] not in RESOLVED]
    resolved_hours = [
        (datetime.fromisoformat(c["resolved_at"]) - datetime.fromisoformat(c["opened_at"])).total_seconds() / 3600
        for c in cases
        if c["state"] in RESOLVED and c.get("resolved_at")
        and datetime.fromisoformat(c["resolved_at"]) >= start
    ]

    submitters: dict[str, int] = {}
    for r in window:
        name = r.get("submitted_by", {}).get("name", "Unknown")
        submitters[name] = submitters.get(name, 0) + 1

    return {
        "days": days,
        "period_start": start.isoformat(timespec="seconds"),
        "period_end": now.isoformat(timespec="seconds"),
        "total": len(window),
        "by_status": {s: sum(r["status"] == s for r in window) for s in STATUSES},
        "daily": [{"date": day.isoformat(), **counts} for day, counts in sorted(daily.items())],
        "top_rules": sorted(rules.values(), key=lambda e: (-e["count"], e["title"]))[:8],
        "cases": {
            "active": len(active),
            "by_state": {s: sum(c["state"] == s for c in cases) for s in ("open", "in_review", "escalated")},
            "overdue": sum(datetime.fromisoformat(c["due_at"]) < now for c in active),
            "resolved_in_period": len(resolved_hours),
            "avg_hours_to_resolve": round(sum(resolved_hours) / len(resolved_hours), 1) if resolved_hours else None,
        },
        "by_submitter": [
            {"name": name, "count": count}
            for name, count in sorted(submitters.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }


# --- Digest ---

def overdue_cases(reviews: list[dict], now: datetime) -> list[dict]:
    rows = [
        r for r in reviews
        if r.get("case") and r["case"]["state"] not in RESOLVED and datetime.fromisoformat(r["case"]["due_at"]) < now
    ]
    return sorted(rows, key=lambda r: r["case"]["due_at"])


def build_digest(
    reviews: list[dict], *, now: datetime, days: int, trigger: str, created_by: dict, app_url: str = "",
) -> dict:
    """A dated snapshot for the compliance team: numbers, top rules, and overdue cases."""
    summary = summarize(reviews, now=now, days=days)
    overdue = overdue_cases(reviews, now)
    period = "the last 24 hours" if days == 1 else f"the last {days} days"
    by_status, cases = summary["by_status"], summary["cases"]

    lines = [
        f"CyanGuard compliance digest for {period}",
        f"{summary['period_start'][:10]} to {summary['period_end'][:10]} (UTC)",
        "",
        f"AI outputs reviewed: {summary['total']}",
        f"  Pass: {by_status['PASS']}   Needs review: {by_status['NEEDS_REVIEW']}   Fail: {by_status['FAIL']}",
        "",
        f"Open cases: {cases['active']}   Overdue: {cases['overdue']}   Resolved in period: {cases['resolved_in_period']}",
    ]
    if cases["avg_hours_to_resolve"] is not None:
        lines.append(f"Average time to resolve: {cases['avg_hours_to_resolve']} hours")
    if summary["top_rules"]:
        lines += ["", "Most-triggered rules:"]
        lines += [f"  {e['count']}x  {e['title']} [{e['severity'].upper()}]" for e in summary["top_rules"][:5]]
    if overdue:
        lines += ["", f"Overdue cases ({len(overdue)}):"]
        for r in overdue[:10]:
            assignee = r["case"]["assignee"]["name"] if r["case"]["assignee"] else "Unassigned"
            link = f" {app_url}case.html?id={r['id']}" if app_url else ""
            lines.append(f"  - {r['status'].replace('_', ' ')}, due {r['case']['due_at'][:16]}, {assignee}:{link}")
        if len(overdue) > 10:
            lines.append(f"  … and {len(overdue) - 10} more")
    if app_url:
        lines += ["", f"Open the Reports page: {app_url}reports.html"]

    return {
        "id": str(uuid.uuid4()),
        "created_at": now.isoformat(timespec="milliseconds"),
        "trigger": trigger,  # "manual" or "scheduled"
        "created_by": created_by,
        "days": days,
        "period_start": summary["period_start"],
        "period_end": summary["period_end"],
        "total": summary["total"],
        "by_status": by_status,
        "cases": cases,
        "top_rules": summary["top_rules"][:5],
        "overdue": [{"id": r["id"], "status": r["status"], "due_at": r["case"]["due_at"]} for r in overdue],
        "subject": f"[CyanGuard] Compliance digest: {summary['total']} reviewed, "
                   f"{by_status['FAIL']} failed, {cases['overdue']} overdue",
        "body": "\n".join(lines),
    }


# --- CSV export ---

CSV_COLUMNS = [
    "review_id", "created_at", "submitted_by", "result", "safety_score", "flag_count", "rules",
    "case_state", "priority", "assignee", "due_at", "resolved_at", "source", "ai_output",
]


def _cell(value) -> str:
    """Stop spreadsheet apps from running AI output as a formula (CSV injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def reviews_csv(reviews: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for r in sorted(reviews, key=lambda r: r["created_at"], reverse=True):
        case = r.get("case") or {}
        writer.writerow([_cell(v) for v in (
            r["id"], r["created_at"], r.get("submitted_by", {}).get("name", "Unknown"), r["status"], r["score"],
            len(r["flags"]), " ".join(sorted({f["rule_id"] for f in r["flags"]})),
            case.get("state", "no case"), case.get("priority", ""), (case.get("assignee") or {}).get("name", ""),
            case.get("due_at", ""), case.get("resolved_at", ""), r.get("source", ""), r["text"],
        )])
    return out.getvalue()
