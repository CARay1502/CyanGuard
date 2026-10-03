"""AWS Lambda entry point. Set the Lambda handler to `lambda_handler.handler`."""
import os

# On Lambda, default to AWS mode. Local mode would try to write files to the
# read-only deployment folder.
os.environ.setdefault("APP_MODE", "aws")

from mangum import Mangum  # noqa: E402

from app.jobs import run_scheduled_task  # noqa: E402
from app.main import app  # noqa: E402

http_handler = Mangum(app)


def handler(event, context):
    # EventBridge Scheduler sends {"cyanguard_task": "digest"}; web requests go to FastAPI.
    if isinstance(event, dict) and "cyanguard_task" in event:
        return run_scheduled_task(event["cyanguard_task"])
    return http_handler(event, context)
