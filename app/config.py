"""App settings, read from environment variables (or a .env file)."""
import os
from pathlib import Path

# Minimal .env loader so local mode needs no extra dependencies.
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

APP_MODE = os.getenv("APP_MODE", "local").lower()  # "local" or "aws"
if APP_MODE not in ("local", "aws"):
    raise ValueError(f"APP_MODE must be 'local' or 'aws', got {APP_MODE!r}")

# Local mode
REVIEWS_FILE = os.getenv("REVIEWS_FILE", "data/reviews.json")

# AWS mode
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
REVIEWS_TABLE = os.getenv("REVIEWS_TABLE", "cyanguard-reviews")
# Model that plays "Cyan" (the assistant being reviewed).
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
# Model that performs the compliance review.
COMPLIANCE_MODEL_ID = os.getenv("COMPLIANCE_MODEL_ID", BEDROCK_MODEL_ID)
