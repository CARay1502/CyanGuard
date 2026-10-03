"""Compliance checking: a local rule engine, or a Bedrock model acting as reviewer.

Both checkers return the same list of flags. `build_report` then turns flags into
a score and status the same way in both modes, so results are comparable.
"""
import json
import re
from typing import Protocol

from app.services.rules import INVESTMENT_TERMS, RISK_TERMS, RULES, RULES_BY_ID, Rule

SEVERITY_PENALTY = {"high": 30, "medium": 15, "low": 5}


class ComplianceChecker(Protocol):
    name: str

    def check(self, text: str) -> list[dict]: ...


def make_flag(rule: Rule, text: str, start: int | None, end: int | None, explanation: str = "") -> dict:
    return {
        "rule_id": rule.id,
        "title": rule.title,
        "severity": rule.severity,
        "citation": rule.citation,
        "url": rule.url,
        "excerpt": text[start:end] if start is not None else "",
        "start": start,
        "end": end,
        "explanation": explanation or rule.description,
        "suggestion": rule.suggestion,
    }


class LocalRuleChecker:
    """Regex screening against the rule catalog. No AWS needed."""

    name = "local-rules"

    def check(self, text: str) -> list[dict]:
        flags = []
        for rule in RULES:
            for pattern in rule.patterns:
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    flags.append(make_flag(rule, text, m.start(), m.end()))

        mentions_investing = re.search(INVESTMENT_TERMS, text, re.IGNORECASE)
        mentions_risk = re.search(RISK_TERMS, text, re.IGNORECASE)
        if mentions_investing and not mentions_risk:
            flags.append(make_flag(RULES_BY_ID["MISSING_RISK_DISCLOSURE"], text, None, None))

        return sorted(flags, key=lambda f: (f["start"] is None, f["start"] or 0))


class BedrockComplianceChecker:
    """Asks a Bedrock model to review the text against the rule catalog."""

    name = "bedrock-reviewer"

    def __init__(self, model_id: str, region: str):
        import boto3  # imported lazily so local mode doesn't need boto3

        self.client = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model_id

    def check(self, text: str) -> list[dict]:
        catalog = "\n".join(f"- {r.id}: {r.title}. {r.description} ({r.citation})" for r in RULES)
        system = (
            "You are a FINRA/SEC compliance reviewer for a broker-dealer. Review the AI assistant "
            "response for violations of the rules below. Only flag real issues. For each flag, "
            "quote the exact offending excerpt verbatim from the response (empty string if the issue "
            "is something missing, like a risk disclosure).\n\nRules:\n" + catalog
        )
        tool = {
            "toolSpec": {
                "name": "report_flags",
                "description": "Report compliance flags found in the response.",
                "inputSchema": {"json": {
                    "type": "object",
                    "properties": {"flags": {"type": "array", "items": {
                        "type": "object",
                        "properties": {
                            "rule_id": {"type": "string", "enum": [r.id for r in RULES]},
                            "excerpt": {"type": "string"},
                            "explanation": {"type": "string"},
                        },
                        "required": ["rule_id", "excerpt", "explanation"],
                    }}},
                    "required": ["flags"],
                }},
            }
        }
        response = self.client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": f"<response>\n{text}\n</response>"}]}],
            toolConfig={"tools": [tool], "toolChoice": {"tool": {"name": "report_flags"}}},
            inferenceConfig={"maxTokens": 2048},
        )
        tool_input = next(
            block["toolUse"]["input"]
            for block in response["output"]["message"]["content"]
            if "toolUse" in block
        )
        if isinstance(tool_input, str):
            tool_input = json.loads(tool_input)

        flags = []
        for raw in tool_input.get("flags", []):
            rule = RULES_BY_ID.get(raw.get("rule_id"))
            if rule is None:
                continue
            excerpt = raw.get("excerpt", "")
            start = text.find(excerpt) if excerpt else -1
            if start >= 0:
                flags.append(make_flag(rule, text, start, start + len(excerpt), raw.get("explanation", "")))
            else:
                flag = make_flag(rule, text, None, None, raw.get("explanation", ""))
                flag["excerpt"] = excerpt
                flags.append(flag)
        return flags


def build_report(flags: list[dict]) -> dict:
    """Score and classify a set of flags. Any high-severity flag fails the response."""
    counts = {sev: sum(f["severity"] == sev for f in flags) for sev in SEVERITY_PENALTY}
    score = max(0, 100 - sum(SEVERITY_PENALTY[f["severity"]] for f in flags))
    if counts["high"]:
        status = "FAIL"
    elif flags:
        status = "NEEDS_REVIEW"
    else:
        status = "PASS"
    return {"status": status, "score": score, "counts": counts, "flags": flags}
