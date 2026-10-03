"""Picks local or AWS implementations based on APP_MODE."""
import secrets
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, HTTPException, Request

from app import config
from app.services.auth import SESSION_COOKIE, read_session, role_at_least
from app.services.compliance import BedrockComplianceChecker, ComplianceChecker, LocalRuleChecker
from app.services.cyan import BedrockCyan, CyanModel, SyntheticCyan
from app.services.storage import REVIEWS, USERS, Database, DynamoDatabase, LocalDatabase, Storage


@lru_cache
def get_db() -> Database:
    if config.APP_MODE == "aws":
        return DynamoDatabase(config.DATA_TABLE, config.AWS_REGION)
    return LocalDatabase(config.DATA_DIR)


def get_reviews(db: Database = Depends(get_db)) -> Storage:
    return db.collection(REVIEWS)


def get_users(db: Database = Depends(get_db)) -> Storage:
    return db.collection(USERS)


# --- Login ---

@lru_cache
def get_session_secret() -> str:
    """The key that signs session cookies.

    AWS mode requires SESSION_SECRET (a Lambda environment variable). Locally, a
    random secret is generated once and saved in DATA_DIR, so sessions survive restarts.
    """
    if config.SESSION_SECRET:
        return config.SESSION_SECRET
    if config.APP_MODE == "aws":
        raise RuntimeError("SESSION_SECRET is not set. Add it as a Lambda environment variable.")
    path = Path(config.DATA_DIR) / ".session_secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(32))
    return path.read_text().strip()


def get_current_user(request: Request, users: Storage = Depends(get_users)) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = read_session(token, get_session_secret()) if token else None
    user = users.get(user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def require_role(minimum: str):
    """Route dependency: the signed-in user, if their role is at least `minimum`."""

    def dependency(user: dict = Depends(get_current_user)) -> dict:
        if not role_at_least(user["role"], minimum):
            raise HTTPException(status_code=403, detail="Your role can't do this")
        return user

    return dependency


@lru_cache
def get_cyan() -> CyanModel:
    if config.APP_MODE == "aws":
        return BedrockCyan(config.BEDROCK_MODEL_ID, config.AWS_REGION)
    return SyntheticCyan()


@lru_cache
def get_checker() -> ComplianceChecker:
    if config.APP_MODE == "aws":
        return BedrockComplianceChecker(config.COMPLIANCE_MODEL_ID, config.AWS_REGION)
    return LocalRuleChecker()
