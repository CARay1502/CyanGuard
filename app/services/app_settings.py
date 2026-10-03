"""App settings that admins change from the Settings page.

Stored as one record ("app") in the settings collection, so they apply in both
local and AWS mode and survive redeploys. Deployment config (APP_MODE, table names,
secrets) stays in environment variables instead.
"""
from typing import Literal

from pydantic import BaseModel, Field

from app.services.storage import Storage

SETTINGS_ID = "app"


class AppSettings(BaseModel):
    # Email case alerts through Amazon SNS (AWS mode with SNS_TOPIC_ARN set).
    # Notifications are always saved to the in-app outbox either way.
    email_notifications: bool = False
    # Which results send a "case opened" notification. Escalations always notify.
    notify_on: list[Literal["FAIL", "NEEDS_REVIEW"]] = ["FAIL", "NEEDS_REVIEW"]
    # How long compliance has to resolve a case, by priority.
    sla_hours_high: int = Field(default=4, ge=1, le=720)
    sla_hours_normal: int = Field(default=24, ge=1, le=720)
    # How many days the scheduled compliance digest covers.
    digest_days: int = Field(default=7, ge=1, le=90)


def load_settings(settings: Storage) -> AppSettings:
    stored = settings.get(SETTINGS_ID) or {}
    stored.pop("id", None)
    stored.pop("updated_at", None)
    stored.pop("updated_by", None)
    return AppSettings(**stored)


def save_settings(settings: Storage, values: AppSettings, *, by: dict, at: str) -> AppSettings:
    settings.put({"id": SETTINGS_ID, **values.model_dump(), "updated_at": at, "updated_by": by})
    return values
