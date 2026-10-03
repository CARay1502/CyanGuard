import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config
from app.deps import (
    get_checker,
    get_current_user,
    get_cyan,
    get_db,
    get_email_sender,
    get_outbox,
    get_reviews,
    get_session_secret,
    get_settings_store,
    get_users,
    require_role,
)
from app.jobs import reviews_with_cases, run_digest
from app.services.app_settings import AppSettings, load_settings, save_settings
from app.services.auth import (
    SESSION_COOKIE,
    public_user,
    role_at_least,
    seed_demo_users,
    sign_session,
    verify_password,
)
from app.services.cases import RESOLVED, CaseError, apply_action, ensure_case, new_case
from app.services.compliance import ComplianceChecker, build_report
from app.services.cyan import SCENARIOS, SCENARIOS_BY_ID, SCRIPTED_MODEL, CyanModel
from app.services.notify import EmailSender, notify
from app.services.reports import in_window, reviews_csv, summarize
from app.services.rules import RULES
from app.services.storage import DIGESTS, Database, Storage

app = FastAPI(title="CyanGuard")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class GenerateIn(BaseModel):
    prompt: str = Field(min_length=1)
    # A demo scenario ID: return its scripted output instead of calling the model.
    scenario: str | None = None


class ReviewIn(BaseModel):
    text: str = Field(min_length=1)
    prompt: str = ""
    source: str = "manual"


class CaseActionIn(BaseModel):
    action: Literal["assign", "approve", "reject", "escalate", "reopen"]
    note: str = Field(default="", max_length=2000)
    assignee_id: str | None = None  # for "assign"; defaults to the signed-in user


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def case_url(request: Request, review_id: str) -> str:
    return f"{request.base_url}case.html?id={review_id}"


def can_see_review(user: dict, review: dict) -> bool:
    """Analysts see their own reviews; compliance officers and admins see all."""
    if role_at_least(user["role"], "compliance"):
        return True
    return review.get("submitted_by", {}).get("id") == user["id"]


@app.get("/health")
def health():
    return {"status": "ok", "mode": config.APP_MODE}


# --- Login ---

@app.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, users: Storage = Depends(get_users)):
    if config.DEMO_PASSWORD:
        seed_demo_users(users, config.DEMO_PASSWORD)
    user = users.get(body.username.strip().lower())
    if not verify_password(body.password, user["password_hash"] if user else None):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    max_age = config.SESSION_HOURS * 3600
    response.set_cookie(
        SESSION_COOKIE,
        sign_session(user["id"], get_session_secret(), max_age),
        max_age=max_age,
        httponly=True,  # not readable by JavaScript
        samesite="lax",  # not sent on cross-site form posts
        secure=request.url.scheme == "https",
        path="/",
    )
    return public_user(user)


@app.post("/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")


@app.get("/auth/me")
def me(user: dict = Depends(get_current_user)):
    return public_user(user)


# --- Compliance ---

@app.get("/rules")
def list_rules(user: dict = Depends(get_current_user)):
    return [{k: v for k, v in asdict(r).items() if k != "patterns"} for r in RULES]


@app.get("/cyan/scenarios")
def list_scenarios(user: dict = Depends(require_role("analyst"))):
    """The demo scenario buttons. Outputs stay on the server until a button is used."""
    return [{"id": s.id, "label": s.label, "prompt": s.prompt} for s in SCENARIOS]


@app.post("/cyan/generate")
def generate(
    body: GenerateIn,
    cyan: CyanModel = Depends(get_cyan),
    user: dict = Depends(require_role("analyst")),
):
    if body.scenario is not None:
        scenario = SCENARIOS_BY_ID.get(body.scenario)
        if scenario is None:
            raise HTTPException(status_code=404, detail="Unknown demo scenario")
        # Scripted on purpose, in every mode: real models' own safeguards would block these.
        return {"output": scenario.output, "model": SCRIPTED_MODEL, "scenario": scenario.id}
    return {"output": cyan.generate(body.prompt), "model": cyan.name, "scenario": None}


@app.post("/reviews", status_code=201)
def create_review(
    body: ReviewIn,
    request: Request,
    checker: ComplianceChecker = Depends(get_checker),
    reviews: Storage = Depends(get_reviews),
    settings_store: Storage = Depends(get_settings_store),
    outbox: Storage = Depends(get_outbox),
    email: EmailSender | None = Depends(get_email_sender),
    user: dict = Depends(require_role("analyst")),
):
    now = now_utc()
    review = {
        "id": str(uuid.uuid4()),
        "created_at": now.isoformat(timespec="seconds"),
        "prompt": body.prompt,
        "text": body.text,
        "source": body.source,
        "checker": checker.name,
        "submitted_by": {"id": user["id"], "name": user["name"]},
        **build_report(checker.check(body.text)),
    }
    settings = load_settings(settings_store)
    review["case"] = new_case(review, settings, now)
    reviews.put(review)

    if review["case"] and review["status"] in settings.notify_on:
        notify(
            outbox,
            email if settings.email_notifications else None,
            event="case_opened",
            review=review,
            case_url=case_url(request, review["id"]),
            now=now,
        )
    return review


@app.get("/reviews")
def list_reviews(reviews: Storage = Depends(get_reviews), user: dict = Depends(get_current_user)):
    visible = [r for r in reviews.list() if can_see_review(user, r)]
    return sorted(visible, key=lambda r: r["created_at"], reverse=True)


@app.get("/reviews/{review_id}")
def get_review(
    review_id: str,
    reviews: Storage = Depends(get_reviews),
    settings_store: Storage = Depends(get_settings_store),
    user: dict = Depends(get_current_user),
):
    review = reviews.get(review_id)
    if review is None or not can_see_review(user, review):
        raise HTTPException(status_code=404, detail="Review not found")
    ensure_case(review, load_settings(settings_store))
    return review


@app.delete("/reviews/{review_id}", status_code=204)
def delete_review(
    review_id: str,
    reviews: Storage = Depends(get_reviews),
    user: dict = Depends(require_role("admin")),
):
    reviews.delete(review_id)


class FrontendFiles(StaticFiles):
    """Static files that browsers re-check on every load (cheap: unchanged files return 304).

    Without this, browsers may keep showing an old page or script after a redeploy.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


# --- Cases (compliance review workflow) ---

PRIORITY_ORDER = {"high": 0, "normal": 1}


@app.get("/cases")
def list_cases(
    state: Literal["active", "resolved", "all"] = "active",
    reviews: Storage = Depends(get_reviews),
    settings_store: Storage = Depends(get_settings_store),
    user: dict = Depends(require_role("compliance")),
):
    """Flagged reviews with their case. Active cases: highest priority, then soonest due."""
    settings = load_settings(settings_store)
    cases = [r for r in reviews.list() if ensure_case(r, settings)]
    if state == "active":
        cases = [r for r in cases if r["case"]["state"] not in RESOLVED]
        return sorted(cases, key=lambda r: (PRIORITY_ORDER[r["case"]["priority"]], r["case"]["due_at"]))
    if state == "resolved":
        cases = [r for r in cases if r["case"]["state"] in RESOLVED]
    return sorted(cases, key=lambda r: r["created_at"], reverse=True)


@app.post("/reviews/{review_id}/case")
def act_on_case(
    review_id: str,
    body: CaseActionIn,
    request: Request,
    reviews: Storage = Depends(get_reviews),
    users: Storage = Depends(get_users),
    settings_store: Storage = Depends(get_settings_store),
    outbox: Storage = Depends(get_outbox),
    email: EmailSender | None = Depends(get_email_sender),
    user: dict = Depends(require_role("compliance")),
):
    review = reviews.get(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    settings = load_settings(settings_store)
    ensure_case(review, settings)

    assignee = None
    if body.action == "assign" and body.assignee_id:
        assignee = users.get(body.assignee_id)
        if assignee is None:
            raise HTTPException(status_code=400, detail="That user doesn't exist")

    now = now_utc()
    try:
        apply_action(review, body.action, actor=user, now=now, note=body.note, assignee=assignee)
    except CaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    reviews.put(review)

    if body.action == "escalate":
        notify(
            outbox,
            email if settings.email_notifications else None,
            event="case_escalated",
            review=review,
            case_url=case_url(request, review_id),
            now=now,
            note=body.note.strip(),
        )
    return review


@app.get("/users/assignable")
def assignable_users(users: Storage = Depends(get_users), user: dict = Depends(require_role("compliance"))):
    """Compliance officers and admins, who can be assigned cases."""
    return [public_user(u) for u in users.list() if role_at_least(u["role"], "compliance")]


@app.get("/notifications")
def list_notifications(outbox: Storage = Depends(get_outbox), user: dict = Depends(require_role("compliance"))):
    """The most recent case alerts, newest first."""
    return sorted(outbox.list(), key=lambda n: n["created_at"], reverse=True)[:100]


# --- Reports ---

class DigestIn(BaseModel):
    days: int = Field(default=7, ge=1, le=90)


@app.get("/reports/summary")
def report_summary(
    days: int = Query(default=30, ge=1, le=365),
    tz_offset: int = Query(default=0, ge=-840, le=840),  # the browser's Date.getTimezoneOffset()
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("compliance")),
):
    return summarize(reviews_with_cases(db), now=now_utc(), days=days, tz_offset_minutes=tz_offset)


@app.get("/reports/export.csv")
def report_export(
    days: int = Query(default=30, ge=1, le=365),
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("compliance")),
):
    now = now_utc()
    rows = in_window(reviews_with_cases(db), now, days)
    filename = f"cyanguard-reviews-{now.date().isoformat()}-last-{days}-days.csv"
    return Response(
        content=reviews_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/reports/digests")
def list_digests(db: Database = Depends(get_db), user: dict = Depends(require_role("compliance"))):
    return sorted(db.collection(DIGESTS).list(), key=lambda d: d["created_at"], reverse=True)[:50]


@app.post("/reports/digests", status_code=201)
def create_digest(
    body: DigestIn,
    request: Request,
    db: Database = Depends(get_db),
    email: EmailSender | None = Depends(get_email_sender),
    user: dict = Depends(require_role("compliance")),
):
    return run_digest(
        db,
        email,
        now=now_utc(),
        days=body.days,
        trigger="manual",
        created_by={"id": user["id"], "name": user["name"]},
        app_url=str(request.base_url),
    )


# --- Admin settings ---

@app.get("/admin/settings")
def get_app_settings(
    settings_store: Storage = Depends(get_settings_store),
    email: EmailSender | None = Depends(get_email_sender),
    user: dict = Depends(require_role("admin")),
):
    return {
        **load_settings(settings_store).model_dump(),
        # Whether email can actually be sent (AWS mode with SNS_TOPIC_ARN set).
        "email_available": email is not None,
        "mode": config.APP_MODE,
    }


@app.put("/admin/settings")
def update_app_settings(
    body: AppSettings,
    settings_store: Storage = Depends(get_settings_store),
    email: EmailSender | None = Depends(get_email_sender),
    user: dict = Depends(require_role("admin")),
):
    if body.email_notifications and email is None:
        raise HTTPException(
            status_code=400,
            detail="Email can't be turned on: it needs AWS mode and an SNS topic (SNS_TOPIC_ARN).",
        )
    save_settings(
        settings_store,
        body,
        by={"id": user["id"], "name": user["name"]},
        at=now_utc().isoformat(timespec="seconds"),
    )
    return get_app_settings(settings_store, email, user)


# Serve the frontend. Mounted last so the API routes above take priority.
app.mount("/", FrontendFiles(directory=Path(__file__).parent / "static", html=True), name="static")
