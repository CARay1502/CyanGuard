"""Picks local or AWS implementations based on APP_MODE."""
from functools import lru_cache

from app import config
from app.services.compliance import BedrockComplianceChecker, ComplianceChecker, LocalRuleChecker
from app.services.cyan import BedrockCyan, CyanModel, SyntheticCyan
from app.services.storage import DynamoStorage, LocalStorage, Storage


@lru_cache
def get_storage() -> Storage:
    if config.APP_MODE == "aws":
        return DynamoStorage(config.REVIEWS_TABLE, config.AWS_REGION)
    return LocalStorage(config.REVIEWS_FILE)


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
