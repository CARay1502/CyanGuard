import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config
from app.deps import get_checker, get_cyan, get_storage
from app.services.compliance import ComplianceChecker, build_report
from app.services.cyan import CyanModel
from app.services.rules import RULES
from app.services.storage import Storage

app = FastAPI(title="CyanGuard")


class GenerateIn(BaseModel):
    prompt: str = Field(min_length=1)


class ReviewIn(BaseModel):
    text: str = Field(min_length=1)
    prompt: str = ""
    source: str = "manual"


@app.get("/health")
def health():
    return {"status": "ok", "mode": config.APP_MODE}


@app.get("/rules")
def list_rules():
    return [{k: v for k, v in asdict(r).items() if k != "patterns"} for r in RULES]


@app.post("/cyan/generate")
def generate(body: GenerateIn, cyan: CyanModel = Depends(get_cyan)):
    return {"output": cyan.generate(body.prompt), "model": cyan.name}


@app.post("/reviews", status_code=201)
def create_review(
    body: ReviewIn,
    checker: ComplianceChecker = Depends(get_checker),
    storage: Storage = Depends(get_storage),
):
    review = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt": body.prompt,
        "text": body.text,
        "source": body.source,
        "checker": checker.name,
        **build_report(checker.check(body.text)),
    }
    return storage.put(review)


@app.get("/reviews")
def list_reviews(storage: Storage = Depends(get_storage)):
    return sorted(storage.list(), key=lambda r: r["created_at"], reverse=True)


@app.get("/reviews/{review_id}")
def get_review(review_id: str, storage: Storage = Depends(get_storage)):
    review = storage.get(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@app.delete("/reviews/{review_id}", status_code=204)
def delete_review(review_id: str, storage: Storage = Depends(get_storage)):
    storage.delete(review_id)


# Serve the frontend. Mounted last so the API routes above take priority.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
