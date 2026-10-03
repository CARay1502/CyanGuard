"""AWS Lambda entry point. Set the Lambda handler to `lambda_handler.handler`."""
from mangum import Mangum

from app.main import app

handler = Mangum(app)
