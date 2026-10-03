"""Phase B: compliance cases, notifications, and admin settings (all local, no AWS)."""
import os

os.environ["APP_MODE"] = "local"
os.environ.setdefault("DEMO_PASSWORD", "test-password")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.deps import get_db, get_email_sender
from app.main import app
from app.services.app_settings import AppSettings
from app.services.cases import CaseError, apply_action, new_case
from app.services.notify import MAX_SUBJECT, build_message
from app.services.storage import LocalDatabase

PASSWORD = os.environ["DEMO_PASSWORD"]
FAIL_TEXT = "This fund is guaranteed to double. Act now!"
REVIEW_TEXT = "We recommend adding index funds to your portfolio."
PASS_TEXT = "Index funds are popular with many investors."
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


class FakeEmail:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, subject, body):
        if self.fail:
            raise RuntimeError("SNS is down")
        self.sent.append((subject, body))
        return f"msg-{len(self.sent)}"


@pytest.fixture
def db(tmp_path):
    database = LocalDatabase(tmp_path)
    app.dependency_overrides[get_db] = lambda: database
    yield database
    app.dependency_overrides.clear()


@pytest.fixture
def email(db):
    """Pretend AWS email is available."""
    fake = FakeEmail()
    app.dependency_overrides[get_email_sender] = lambda: fake
    return fake


@pytest.fixture
def login(db):
    def _login(username):
        c = TestClient(app)
        assert c.post("/auth/login", json={"username": username, "password": PASSWORD}).status_code == 200
        return c

    return _login


def submit(client, text):
    res = client.post("/reviews", json={"text": text})
    assert res.status_code == 201, res.text
    return res.json()


def act(client, review_id, action, **body):
    return client.post(f"/reviews/{review_id}/case", json={"action": action, **body})


# --- Case rules (pure functions) ---

def make_review(status="FAIL"):
    review = {"id": "r1", "status": status, "flags": [{}], "created_at": NOW.isoformat()}
    review["case"] = new_case(review, AppSettings(), NOW)
    return review


ANALYST = {"id": "analyst", "name": "A", "role": "analyst"}
OFFICER = {"id": "compliance", "name": "C", "role": "compliance"}
ADMIN = {"id": "admin", "name": "Ad", "role": "admin"}


def test_new_case_priority_and_deadline():
    fail, review = make_review("FAIL")["case"], make_review("NEEDS_REVIEW")["case"]
    assert (fail["priority"], fail["due_at"]) == ("high", "2026-10-03T16:00:00+00:00")  # 4h
    assert (review["priority"], review["due_at"]) == ("normal", "2026-10-04T12:00:00+00:00")  # 24h
    assert fail["state"] == "open" and fail["history"][0]["by"]["id"] == "system"
    assert make_review("PASS")["case"] is None


def test_case_lifecycle_records_history():
    review = make_review()
    apply_action(review, "assign", actor=OFFICER, now=NOW)
    assert review["case"]["state"] == "in_review" and review["case"]["assignee"]["id"] == "compliance"
    apply_action(review, "approve", actor=OFFICER, now=NOW, note="Fine after edits")
    assert review["case"]["state"] == "approved" and review["case"]["resolved_at"]
    assert [h["action"] for h in review["case"]["history"]] == ["open", "assign", "approve"]
    assert review["case"]["history"][-1]["note"] == "Fine after edits"


@pytest.mark.parametrize("action", ["reject", "escalate"])
def test_note_required(action):
    with pytest.raises(CaseError, match="note is required"):
        apply_action(make_review(), action, actor=OFFICER, now=NOW, note="  ")


def test_escalated_cases_need_admin_to_resolve():
    review = make_review()
    apply_action(review, "escalate", actor=OFFICER, now=NOW, note="Possible fraud")
    with pytest.raises(CaseError) as exc:
        apply_action(review, "approve", actor=OFFICER, now=NOW)
    assert exc.value.status_code == 403
    apply_action(review, "assign", actor=ADMIN, now=NOW)
    assert review["case"]["state"] == "escalated"  # assigning keeps it escalated
    apply_action(review, "reject", actor=ADMIN, now=NOW, note="Blocked")
    assert review["case"]["state"] == "rejected"


def test_invalid_transitions():
    review = make_review()
    apply_action(review, "approve", actor=OFFICER, now=NOW)
    with pytest.raises(CaseError) as exc:
        apply_action(review, "escalate", actor=OFFICER, now=NOW, note="x")
    assert exc.value.status_code == 409
    with pytest.raises(CaseError, match="Only an admin"):
        apply_action(review, "reopen", actor=OFFICER, now=NOW, note="mistake")
    apply_action(review, "reopen", actor=ADMIN, now=NOW, note="mistake")
    assert review["case"]["state"] == "open" and review["case"]["resolved_at"] is None


def test_cannot_assign_to_analyst():
    with pytest.raises(CaseError, match="only be assigned"):
        apply_action(make_review(), "assign", actor=OFFICER, now=NOW, assignee=ANALYST)


def test_email_message_format():
    review = {**make_review(), "score": 40, "text": "x" * 900, "submitted_by": {"name": "Demo Analyst"},
              "flags": [{"severity": "high", "title": f"Rule {i}", "citation": "FINRA"} for i in range(10)]}
    subject, body = build_message("case_opened", review, "https://app/case.html?id=r1")
    assert subject.startswith("[CyanGuard] New high-priority case: FAIL") and len(subject) <= MAX_SUBJECT
    assert "https://app/case.html?id=r1" in body and "… and 2 more" in body and "Demo Analyst" in body
    assert ("x" * 601) not in body  # long outputs are trimmed


# --- API ---

def test_flagged_review_opens_case_and_outbox_entry(login):
    analyst = login("analyst")
    review = submit(analyst, FAIL_TEXT)
    assert review["case"]["state"] == "open" and review["case"]["priority"] == "high"
    assert submit(analyst, PASS_TEXT)["case"] is None

    notes = login("compliance").get("/notifications").json()
    assert len(notes) == 1
    assert notes[0]["review_id"] == review["id"] and notes[0]["channel"] == "outbox"
    assert notes[0]["delivery"]["status"] == "outbox"
    assert f"case.html?id={review['id']}" in notes[0]["body"]


def test_queue_lists_active_cases_by_priority(login):
    analyst, officer = login("analyst"), login("compliance")
    normal = submit(analyst, REVIEW_TEXT)
    high = submit(analyst, FAIL_TEXT)
    submit(analyst, PASS_TEXT)
    assert [r["id"] for r in officer.get("/cases").json()] == [high["id"], normal["id"]]

    act(officer, high["id"], "approve")
    assert [r["id"] for r in officer.get("/cases").json()] == [normal["id"]]
    assert [r["id"] for r in officer.get("/cases?state=resolved").json()] == [high["id"]]
    assert len(officer.get("/cases?state=all").json()) == 2


def test_case_actions_over_api(login):
    analyst, officer, admin = login("analyst"), login("compliance"), login("admin")
    review = submit(analyst, FAIL_TEXT)

    assert act(analyst, review["id"], "approve").status_code == 403  # analysts can't act
    assert act(officer, review["id"], "reject").status_code == 400  # note required
    assert act(officer, review["id"], "assign", assignee_id="analyst").status_code == 400
    assert act(officer, review["id"], "assign", assignee_id="nobody").status_code == 400

    case = act(officer, review["id"], "assign", assignee_id="admin").json()["case"]
    assert case["assignee"]["id"] == "admin" and case["state"] == "in_review"
    assert act(officer, review["id"], "escalate", note="Needs legal").json()["case"]["state"] == "escalated"
    assert act(officer, review["id"], "approve").status_code == 403
    assert act(admin, review["id"], "reject", note="Blocked").json()["case"]["state"] == "rejected"
    assert act(officer, review["id"], "approve").status_code == 409


def test_escalation_always_notifies(login):
    analyst, officer, admin = login("analyst"), login("compliance"), login("admin")
    admin.put("/admin/settings", json={"notify_on": []})  # no "case opened" alerts
    review = submit(analyst, FAIL_TEXT)
    assert officer.get("/notifications").json() == []

    act(officer, review["id"], "escalate", note="Needs legal")
    notes = officer.get("/notifications").json()
    assert [n["event"] for n in notes] == ["case_escalated"]
    assert "Escalation note: Needs legal" in notes[0]["body"]


def test_legacy_reviews_get_a_case(db, login):
    db.collection("reviews").put({
        "id": "old", "created_at": "2026-10-01T09:00:00+00:00", "text": FAIL_TEXT, "prompt": "", "source": "x",
        "checker": "local-rules", "status": "FAIL", "score": 0, "counts": {}, "flags": [],
    })
    officer = login("compliance")
    assert officer.get("/cases").json()[0]["case"]["opened_at"] == "2026-10-01T09:00:00+00:00"
    assert officer.get("/reviews/old").json()["case"]["state"] == "open"
    act(officer, "old", "approve")
    assert db.collection("reviews").get("old")["case"]["state"] == "approved"  # saved once acted on


def test_assignable_users_are_compliance_and_up(login):
    users = login("compliance").get("/users/assignable").json()
    assert sorted(u["id"] for u in users) == ["admin", "compliance"]
    assert all("password_hash" not in u for u in users)
    assert login("analyst").get("/users/assignable").status_code == 403


# --- Settings and email ---

def test_settings_admin_only_with_defaults(login):
    admin = login("admin")
    settings = admin.get("/admin/settings").json()
    assert settings == {
        "email_notifications": False, "notify_on": ["FAIL", "NEEDS_REVIEW"],
        "sla_hours_high": 4, "sla_hours_normal": 24, "digest_days": 7, "email_available": False, "mode": "local",
    }
    assert login("compliance").get("/admin/settings").status_code == 403
    assert login("compliance").put("/admin/settings", json={}).status_code == 403


def test_settings_validation_and_effect(login):
    admin, analyst = login("admin"), login("analyst")
    assert admin.put("/admin/settings", json={"sla_hours_high": 0}).status_code == 422
    assert admin.put("/admin/settings", json={"notify_on": ["PASS"]}).status_code == 422

    saved = admin.put("/admin/settings", json={"sla_hours_high": 1, "notify_on": ["FAIL"]}).json()
    assert saved["sla_hours_high"] == 1 and saved["notify_on"] == ["FAIL"]
    case = submit(analyst, FAIL_TEXT)["case"]
    opened = datetime.fromisoformat(case["opened_at"])
    assert datetime.fromisoformat(case["due_at"]) - opened == (datetime(2000, 1, 1, 1) - datetime(2000, 1, 1))

    submit(analyst, REVIEW_TEXT)  # NEEDS_REVIEW no longer notifies
    assert [n["status"] for n in admin.get("/notifications").json()] == ["FAIL"]


def test_email_cannot_be_enabled_without_sns(login):
    res = login("admin").put("/admin/settings", json={"email_notifications": True})
    assert res.status_code == 400 and "SNS" in res.json()["detail"]


def test_email_sent_only_when_toggled_on(login, email):
    admin, analyst = login("admin"), login("analyst")
    assert admin.get("/admin/settings").json()["email_available"] is True

    submit(analyst, FAIL_TEXT)  # email available but toggled off
    assert email.sent == []

    admin.put("/admin/settings", json={"email_notifications": True})
    submit(analyst, FAIL_TEXT)
    assert len(email.sent) == 1 and email.sent[0][0].startswith("[CyanGuard]")
    latest = admin.get("/notifications").json()[0]
    assert latest["channel"] == "email" and latest["delivery"] == {"status": "sent", "detail": "SNS message msg-1"}


def test_email_failure_is_recorded_not_raised(login, db):
    failing = FakeEmail(fail=True)
    app.dependency_overrides[get_email_sender] = lambda: failing
    admin, analyst = login("admin"), login("analyst")
    admin.put("/admin/settings", json={"email_notifications": True})

    assert submit(analyst, FAIL_TEXT)["case"]["state"] == "open"  # review still saved
    delivery = admin.get("/notifications").json()[0]["delivery"]
    assert delivery["status"] == "failed" and "SNS is down" in delivery["detail"]


def test_settings_survive_in_storage(db, login):
    login("admin").put("/admin/settings", json={"sla_hours_normal": 48})
    stored = db.collection("settings").get("app")
    assert stored["sla_hours_normal"] == 48 and stored["updated_by"]["id"] == "admin"
