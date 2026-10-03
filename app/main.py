import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config
from app.deps import get_checker, get_cyan, get_current_user, get_reviews, get_session_secret, get_users, require_role
from app.services.auth import (
    SESSION_COOKIE,
    public_user,
    role_at_least,
    seed_demo_users,
    sign_session,
    verify_password,
)
from app.services.compliance import ComplianceChecker, build_report
from app.services.cyan import CyanModel
from app.services.rules import RULES
from app.services.storage import Storage

app = FastAPI(title="CyanGuard")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class GenerateIn(BaseModel):
    prompt: str = Field(min_length=1)


class ReviewIn(BaseModel):
    text: str = Field(min_length=1)
    prompt: str = ""
    source: str = "manual"


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


@app.post("/cyan/generate")
def generate(
    body: GenerateIn,
    cyan: CyanModel = Depends(get_cyan),
    user: dict = Depends(require_role("analyst")),
):
    return {"output": cyan.generate(body.prompt), "model": cyan.name}


@app.post("/reviews", status_code=201)
def create_review(
    body: ReviewIn,
    checker: ComplianceChecker = Depends(get_checker),
    reviews: Storage = Depends(get_reviews),
    user: dict = Depends(require_role("analyst")),
):
    review = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt": body.prompt,
        "text": body.text,
        "source": body.source,
        "checker": checker.name,
        "submitted_by": {"id": user["id"], "name": user["name"]},
        **build_report(checker.check(body.text)),
    }
    return reviews.put(review)


@app.get("/reviews")
def list_reviews(reviews: Storage = Depends(get_reviews), user: dict = Depends(get_current_user)):
    visible = [r for r in reviews.list() if can_see_review(user, r)]
    return sorted(visible, key=lambda r: r["created_at"], reverse=True)


@app.get("/reviews/{review_id}")
def get_review(review_id: str, reviews: Storage = Depends(get_reviews), user: dict = Depends(get_current_user)):
    review = reviews.get(review_id)
    if review is None or not can_see_review(user, review):
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@app.delete("/reviews/{review_id}", status_code=204)
def delete_review(
    review_id: str,
    reviews: Storage = Depends(get_reviews),
    user: dict = Depends(require_role("admin")),
):
    reviews.delete(review_id)


# Serve the frontend. Mounted last so the API routes above take priority.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
