"""AWS Lambda entry point. Set the Lambda handler to `lambda_handler.handler`."""
import os

# On Lambda, default to AWS mode. Local mode would try to write files to the
# read-only deployment folder.
os.environ.setdefault("APP_MODE", "aws")

from mangum import Mangum  # noqa: E402

from app.main import app  # noqa: E402

handler = Mangum(app)
