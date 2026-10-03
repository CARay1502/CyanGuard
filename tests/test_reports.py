"""Phase C: report numbers, CSV export, and the compliance digest (all local, no AWS)."""
import os

os.environ["APP_MODE"] = "local"
os.environ.setdefault("DEMO_PASSWORD", "test-password")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")

import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.deps import get_db, get_email_sender
from app.main import app
from app.services.reports import build_digest, reviews_csv, summarize
from app.services.storage import LocalDatabase

PASSWORD = os.environ["DEMO_PASSWORD"]
NOW = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)


def review(rid, status, *, hours_ago, flags=(), case=None, who="Demo Analyst", text="text"):
    return {
        "id": rid,
        "created_at": (NOW - timedelta(hours=hours_ago)).isoformat(timespec="seconds"),
        "status": status,
        "score": 100,
        "text": text,
        "source": "test",
        "submitted_by": {"id": who.lower(), "name": who},
        "flags": [{"rule_id": r, "title": r.title(), "severity": "high"} for r in flags],
        "case": case,
    }


def case(state, *, opened_hours_ago, due_in_hours, resolved_hours_ago=None):
    return {
        "state": state,
        "priority": "high",
        "opened_at": (NOW - timedelta(hours=opened_hours_ago)).isoformat(timespec="seconds"),
        "due_at": (NOW + timedelta(hours=due_in_hours)).isoformat(timespec="seconds"),
        "resolved_at": (NOW - timedelta(hours=resolved_hours_ago)).isoformat(timespec="seconds")
        if resolved_hours_ago is not None else None,
        "assignee": None,
        "history": [],
    }


REVIEWS = [
    review("a", "PASS", hours_ago=1),
    review("b", "FAIL", hours_ago=2, flags=["GUARANTEE", "PII", "GUARANTEE"],
           case=case("open", opened_hours_ago=2, due_in_hours=-1)),  # overdue
    review("c", "NEEDS_REVIEW", hours_ago=30, flags=["PII"], who="Other",
           case=case("approved", opened_hours_ago=30, due_in_hours=5, resolved_hours_ago=20)),  # 10h to resolve
    review("d", "FAIL", hours_ago=24 * 10, flags=["PII"],
           case=case("escalated", opened_hours_ago=240, due_in_hours=10)),  # outside a 7-day window
]


# --- summarize ---

def test_summary_counts_window_and_cases():
    s = summarize(REVIEWS, now=NOW, days=7)
    assert s["total"] == 3
    assert s["by_status"] == {"PASS": 1, "NEEDS_REVIEW": 1, "FAIL": 1}
    # Cases are a live snapshot, so "d" counts even though it's outside the window.
    assert s["cases"] == {
        "active": 2, "by_state": {"open": 1, "in_review": 0, "escalated": 1},
        "overdue": 1, "resolved_in_period": 1, "avg_hours_to_resolve": 10.0,
    }
    assert s["by_submitter"] == [{"name": "Demo Analyst", "count": 2}, {"name": "Other", "count": 1}]


def test_summary_rules_counted_once_per_review():
    top = {e["rule_id"]: e["count"] for e in summarize(REVIEWS, now=NOW, days=7)["top_rules"]}
    assert top == {"PII": 2, "GUARANTEE": 1}  # "b" repeats GUARANTEE but counts once


def test_daily_series_includes_empty_days_in_order():
    daily = summarize(REVIEWS, now=NOW, days=7)["daily"]
    assert len(daily) == 7 and daily[-1]["date"] == "2026-10-03" and daily[0]["date"] == "2026-09-27"
    assert daily[-1] == {"date": "2026-10-03", "PASS": 1, "NEEDS_REVIEW": 0, "FAIL": 1}
    assert daily[-2] == {"date": "2026-10-02", "PASS": 0, "NEEDS_REVIEW": 1, "FAIL": 0}
    assert sum(d["PASS"] + d["NEEDS_REVIEW"] + d["FAIL"] for d in daily) == 3


def test_daily_series_uses_viewer_timezone():
    # 14:00 UTC is 10:00 in New York (UTC-4, getTimezoneOffset() = 240), same day...
    late = [review("x", "PASS", hours_ago=1)]
    assert summarize(late, now=NOW, days=2, tz_offset_minutes=240)["daily"][-1]["PASS"] == 1
    # ...but 02:00 UTC on Oct 3 is still Oct 2 in New York.
    early = [review("y", "PASS", hours_ago=13)]
    daily = summarize(early, now=NOW, days=2, tz_offset_minutes=240)["daily"]
    assert [d["PASS"] for d in daily] == [1, 0] and daily[0]["date"] == "2026-10-02"


def test_summary_with_no_data():
    s = summarize([], now=NOW, days=7)
    assert s["total"] == 0 and s["cases"]["avg_hours_to_resolve"] is None and s["top_rules"] == []


# --- digest ---

def test_digest_content():
    d = build_digest(REVIEWS, now=NOW, days=7, trigger="manual", created_by={"id": "x", "name": "X"},
                     app_url="https://app/")
    assert d["subject"] == "[CyanGuard] Compliance digest: 3 reviewed, 1 failed, 1 overdue"
    assert [o["id"] for o in d["overdue"]] == ["b"]
    assert "Open cases: 2   Overdue: 1" in d["body"]
    assert "Average time to resolve: 10.0 hours" in d["body"]
    assert "https://app/case.html?id=b" in d["body"] and "https://app/reports.html" in d["body"]


def test_digest_without_app_url_has_no_links():
    d = build_digest(REVIEWS, now=NOW, days=1, trigger="scheduled", created_by={"id": "s", "name": "S"})
    assert "http" not in d["body"] and "the last 24 hours" in d["body"]


# --- CSV ---

def test_csv_columns_and_formula_injection_guard():
    rows = list(csv.reader(io.StringIO(reviews_csv([
        review("a", "PASS", hours_ago=1, text="=HYPERLINK(\"http://evil\")"),
        review("b", "FAIL", hours_ago=2, flags=["PII", "GUARANTEE"], case=case("open", opened_hours_ago=2, due_in_hours=1)),
    ]))))
    header, first, second = rows
    assert header[0] == "review_id" and header[-1] == "ai_output"
    assert first[0] == "a" and first[header.index("ai_output")].startswith("'=")  # neutralised
    assert first[header.index("case_state")] == "no case"
    assert second[header.index("rules")] == "GUARANTEE PII" and second[header.index("case_state")] == "open"


# --- API ---

@pytest.fixture
def db(tmp_path):
    database = LocalDatabase(tmp_path)
    app.dependency_overrides[get_db] = lambda: database
    yield database
    app.dependency_overrides.clear()


@pytest.fixture
def login(db):
    def _login(username):
        c = TestClient(app)
        assert c.post("/auth/login", json={"username": username, "password": PASSWORD}).status_code == 200
        return c

    return _login


def test_report_endpoints_need_compliance_role(login):
    analyst = login("analyst")
    for path in ("/reports/summary", "/reports/export.csv", "/reports/digests"):
        assert analyst.get(path).status_code == 403
    assert analyst.post("/reports/digests", json={}).status_code == 403


def test_summary_and_csv_over_api(login):
    login("analyst").post("/reviews", json={"text": "This fund is guaranteed to double. Act now!"})
    officer = login("compliance")

    s = officer.get("/reports/summary?days=7&tz_offset=240").json()
    assert s["total"] == 1 and s["by_status"]["FAIL"] == 1 and s["cases"]["active"] == 1
    assert officer.get("/reports/summary?days=0").status_code == 422

    res = officer.get("/reports/export.csv?days=7")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert "attachment;" in res.headers["content-disposition"]
    assert len(list(csv.reader(io.StringIO(res.text)))) == 2  # header + 1 review


def test_manual_digest_saved_and_sent_to_outbox(login):
    login("analyst").post("/reviews", json={"text": "This fund is guaranteed to double. Act now!"})
    officer = login("compliance")

    digest = officer.post("/reports/digests", json={"days": 7}).json()
    assert digest["trigger"] == "manual" and digest["created_by"]["id"] == "compliance"
    assert digest["delivery"]["status"] == "outbox"
    assert "http://testserver/reports.html" in digest["body"]
    assert [d["id"] for d in officer.get("/reports/digests").json()] == [digest["id"]]
    events = [n["event"] for n in officer.get("/notifications").json()]
    assert events[0] == "digest"
    assert officer.post("/reports/digests", json={"days": 0}).status_code == 422


def test_digest_emails_when_toggled_on(login):
    sent = []

    class FakeEmail:
        def send(self, subject, body):
            sent.append(subject)
            return "msg-1"

    app.dependency_overrides[get_email_sender] = lambda: FakeEmail()
    login("admin").put("/admin/settings", json={"email_notifications": True})
    digest = login("compliance").post("/reports/digests", json={"days": 1}).json()
    assert digest["delivery"]["status"] == "sent" and sent == [digest["subject"]]


# --- Scheduled digest (EventBridge -> Lambda) ---

def test_lambda_routes_scheduled_task(monkeypatch, tmp_path):
    import lambda_handler
    from app import deps

    database = LocalDatabase(tmp_path)
    monkeypatch.setattr(deps, "get_db", lambda: database)
    database.collection("settings").put({"id": "app", "digest_days": 3})

    result = lambda_handler.handler({"cyanguard_task": "digest"}, None)
    assert result["ok"] is True and result["delivery"] == "outbox"
    digest = database.collection("digests").get(result["digest_id"])
    assert digest["trigger"] == "scheduled" and digest["days"] == 3

    assert lambda_handler.handler({"cyanguard_task": "nope"}, None)["ok"] is False
