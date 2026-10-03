import os

os.environ["APP_MODE"] = "local"

import pytest
from fastapi.testclient import TestClient

from app.deps import get_storage
from app.main import app
from app.services.compliance import LocalRuleChecker, build_report
from app.services.cyan import SAMPLES
from app.services.storage import LocalStorage


@pytest.fixture
def client(tmp_path):
    app.dependency_overrides[get_storage] = lambda: LocalStorage(str(tmp_path / "reviews.json"))
    yield TestClient(app)
    app.dependency_overrides.clear()


def check(text):
    return build_report(LocalRuleChecker().check(text))


def rule_ids(report):
    return {f["rule_id"] for f in report["flags"]}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "mode": "local"}


def test_compliant_sample_passes():
    report = check(SAMPLES[0]["text"])
    assert report["status"] == "PASS", report["flags"]
    assert report["score"] == 100


def test_guarantee_sample_fails():
    report = check(SAMPLES[1]["text"])
    assert report["status"] == "FAIL"
    assert "GUARANTEE" in rule_ids(report)


def test_stock_sample_flags():
    ids = rule_ids(check(SAMPLES[2]["text"]))
    assert {"PROJECTION", "EXAGGERATED", "TESTIMONIAL", "PRESSURE", "PERSONALIZED_REC"} <= ids


def test_crypto_sample_flags():
    ids = rule_ids(check(SAMPLES[3]["text"]))
    assert {"SUITABILITY", "PII", "MISSING_RISK_DISCLOSURE"} <= ids


def test_negated_guarantee_not_flagged():
    assert "GUARANTEE" not in rule_ids(check("Returns are not guaranteed and you may lose money."))


def test_minor_issue_needs_review():
    assert check("Index funds are popular with many investors.")["status"] == "NEEDS_REVIEW"


def test_flag_spans_match_excerpt():
    text = SAMPLES[2]["text"]
    for flag in check(text)["flags"]:
        if flag["start"] is not None:
            assert text[flag["start"]:flag["end"]] == flag["excerpt"]


def test_generate_then_review_flow(client):
    out = client.post("/cyan/generate", json={"prompt": "Is there a guaranteed safe fund?"}).json()
    review = client.post("/reviews", json={"text": out["output"], "source": out["model"]}).json()
    assert review["status"] == "FAIL"
    assert review["checker"] == "local-rules"
    assert client.get(f"/reviews/{review['id']}").json()["id"] == review["id"]
    assert len(client.get("/reviews").json()) == 1
    client.delete(f"/reviews/{review['id']}")
    assert client.get(f"/reviews/{review['id']}").status_code == 404


def test_rules_endpoint(client):
    rules = client.get("/rules").json()
    assert all("citation" in r and "patterns" not in r for r in rules)


def test_frontend_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "CyanGuard" in res.text
