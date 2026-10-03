"""SEC / FINRA rule catalog used by both compliance checkers.

Each rule has a citation and link so every flag can point back to its source.
`patterns` are only used by the local checker; the Bedrock checker reads the
title and description instead.

This catalog is a starting point for screening, not legal advice. Have your
compliance team review and extend it.
"""
from dataclasses import dataclass

FINRA_2210 = "https://www.finra.org/rules-guidance/rulebooks/finra-rules/2210"


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    severity: str  # "high" | "medium" | "low"
    citation: str
    url: str
    description: str
    suggestion: str
    patterns: tuple[str, ...] = ()


RULES: tuple[Rule, ...] = (
    Rule(
        id="GUARANTEE",
        title="Guarantee of returns or against loss",
        severity="high",
        citation="FINRA Rule 2150(b); FINRA Rule 2210(d)(1)(B)",
        url="https://www.finra.org/rules-guidance/rulebooks/finra-rules/2150",
        description="Promising returns, guaranteeing against loss, or calling an investment risk-free.",
        suggestion="Remove guarantee language and state that investments can lose value.",
        patterns=(
            r"(?<!not )(?<!no )(?<!never )\bguarantee(d|s)?\b",
            r"\bcan(no|')t lose\b",
            r"\brisk[- ]free\b",
            r"\b(no|zero) risk\b",
        ),
    ),
    Rule(
        id="PROJECTION",
        title="Prediction or projection of performance",
        severity="high",
        citation="FINRA Rule 2210(d)(1)(F)",
        url=FINRA_2210,
        description="Predicting or projecting future performance, or implying past performance will recur.",
        suggestion="Remove forecasts. If discussing history, add that past performance does not guarantee future results.",
        patterns=(
            r"\bwill (double|triple|soar|skyrocket|grow|rise|go up|increase|outperform|return|beat)\b",
            r"\b(expect|projected|forecast)\w* (returns?|gains?|growth) of \d+(\.\d+)?%",
            r"\bis going to (double|triple|soar|rise|go up)\b",
        ),
    ),
    Rule(
        id="EXAGGERATED",
        title="Exaggerated or promissory claim",
        severity="medium",
        citation="FINRA Rule 2210(d)(1)(B)",
        url=FINRA_2210,
        description="False, exaggerated, unwarranted, or promissory statements.",
        suggestion="Replace superlatives with factual, balanced descriptions.",
        patterns=(
            r"\b(sure thing|can't miss|no[- ]brainer|once[- ]in[- ]a[- ]lifetime|to the moon)\b",
            r"\b(best|safest|surest) (investment|stock|fund|bet)\b",
        ),
    ),
    Rule(
        id="PRESSURE",
        title="High-pressure or urgent language",
        severity="medium",
        citation="FINRA Rule 2210(d)(1)(A)",
        url=FINRA_2210,
        description="Urgency or pressure tactics that undermine a fair and balanced presentation.",
        suggestion="Remove time pressure. Let the customer decide at their own pace.",
        patterns=(
            r"\bact (now|fast|quickly)\b",
            r"\bdon'?t miss (out|this)\b",
            r"\blimited[- ]time\b",
            r"\bbefore it'?s too late\b",
        ),
    ),
    Rule(
        id="TESTIMONIAL",
        title="Testimonial or cherry-picked client result",
        severity="medium",
        citation="FINRA Rule 2210(d)(6); SEC Rule 206(4)-1 (Marketing Rule)",
        url="https://www.ecfr.gov/current/title-17/section-275.206(4)-1",
        description="Client testimonials or individual results presented without the required disclosures.",
        suggestion="Remove the testimonial or add required disclosures (compensation, conflicts, not representative).",
        patterns=(
            r"\b(one of )?our clients? (made|earned|saw|gained|love[sd]?|doubled)\b",
            r"\bclients? (have )?(made|earned|gained) \d+",
        ),
    ),
    Rule(
        id="SUITABILITY",
        title="Unsuitable concentration recommendation",
        severity="high",
        citation="FINRA Rule 2111; SEC Regulation Best Interest (17 CFR 240.15l-1)",
        url="https://www.finra.org/rules-guidance/rulebooks/finra-rules/2111",
        description="Recommending concentrating all savings in one investment without knowing the customer's profile.",
        suggestion="Avoid concentration advice. Recommend reviewing goals, risk tolerance, and time horizon first.",
        patterns=(
            r"\b(all|entire|everything|100%)( of)? (your |their )?(retirement|savings|portfolio|401\(?k\)?|nest egg|money)\b",
            r"\bput everything (in|into)\b",
        ),
    ),
    Rule(
        id="PERSONALIZED_REC",
        title="Personalized recommendation without customer profile",
        severity="medium",
        citation="SEC Regulation Best Interest (17 CFR 240.15l-1)",
        url="https://www.ecfr.gov/current/title-17/section-240.15l-1",
        description="Directly telling the customer to buy or sell a specific security without a documented profile.",
        suggestion="Reframe as general education, or route to a licensed representative for a recommendation.",
        patterns=(
            r"\byou should (definitely )?(buy|sell|invest in|move into)\b",
            r"\bi recommend (buying|selling|you buy|you sell)\b",
        ),
    ),
    Rule(
        id="PII",
        title="Customer personal information exposed",
        severity="high",
        citation="SEC Regulation S-P (17 CFR Part 248)",
        url="https://www.ecfr.gov/current/title-17/chapter-II/part-248",
        description="Social Security numbers, account numbers, or other nonpublic personal information.",
        suggestion="Redact the personal information before the response is shown or stored.",
        patterns=(
            r"\b\d{3}-\d{2}-\d{4}\b",
            r"\baccount (number|no\.?|#)\s*:?\s*\d{6,}\b",
        ),
    ),
    Rule(
        id="PROMPT_INJECTION",
        title="Prompt injection or safety override attempt",
        severity="high",
        citation="OWASP Top 10 for LLM Applications, LLM01: Prompt Injection; FINRA Rule 3110 (Supervision)",
        url="https://genai.owasp.org/llmrisk/llm01-prompt-injection/",
        description=(
            "Instructions to ignore prior instructions or disable safety and compliance controls. "
            "Signals the assistant was manipulated and its output can't be trusted."
        ),
        suggestion="Block the response, log the incident, and review the input that produced it.",
        patterns=(
            r"\bignore (all |any )?(previous|prior|above|earlier)( \w+)? (instructions|restrictions|rules|guidelines|prompts?)\b",
            r"\bdisregard (all |any |the )?(previous|prior|above|earlier|system)( \w+)? (instructions|restrictions|rules|guidelines|prompts?)\b",
            r"\b(disable|bypass|override|turn off|deactivate) (the |all |any |your )?(safety|compliance|security|guard)\w*( (rules|checks|controls|filters|guardrails|settings))?",
            r"\b(jailbreak|developer mode)\b",
        ),
    ),
    Rule(
        id="UNAPPROVED_ACTION",
        title="Action without required human approval",
        severity="high",
        citation="FINRA Rule 3110 (Supervision); FINRA Rule 2210(b)(1) (Principal approval)",
        url="https://www.finra.org/rules-guidance/rulebooks/finra-rules/3110",
        description=(
            "Executing, sending, or distributing a recommendation or transaction while skipping "
            "advisor, principal, or compliance review."
        ),
        suggestion="Hold the action and route it to a registered principal or advisor for approval.",
        patterns=(
            r"\bwithout (waiting for |any |the |prior |first getting )?(an? )?(advisor|human|principal|supervisor|compliance)('s)? (approval|review|sign[- ]?off|authorization)",
            r"\bskip(ping)? (the )?(advisor|human|principal|compliance) (approval|review)",
            r"\b(send|email|distribute|blast)\w*\b[^.]{0,40}\bto all (of )?(our |the |your )?clients\b",
        ),
    ),
    Rule(
        id="MISSING_RISK_DISCLOSURE",
        title="Investment recommendation without risk disclosure",
        severity="medium",
        citation="FINRA Rule 2210(d)(1)(A)",
        url=FINRA_2210,
        description=(
            "Recommends or promotes an investment, or makes a performance claim, without mentioning risk, "
            "so it isn't fair and balanced. Neutral mentions of investments don't count."
        ),
        suggestion="Add a balanced risk statement, e.g. 'All investments involve risk, including loss of principal.'",
    ),
)

RULES_BY_ID = {rule.id: rule for rule in RULES}

# Used by MISSING_RISK_DISCLOSURE in the local checker: the text mentions investing and
# makes a recommendation or promotional claim, but never mentions risk.
INVESTMENT_TERMS = r"\b(invest\w*|stocks?|funds?|etfs?|bonds?|crypto\w*|returns?|portfolio|securit(y|ies))\b"
RISK_TERMS = r"\b(risks?|risky|volatil\w*|lose (some|all|money|value)|loss of principal|not guaranteed|past performance)\b"
RECOMMENDATION_TERMS = (
    r"\b(you should|you need to|i recommend|we recommend|recommend(?:ing|ed)?|buy|sell|invest in"
    r"|move (?:your|the)|allocate|allocation to|guaranteed|guarantee|risk[- ]?free|sure thing|will double)\b"
    # Percentages sit outside the group above: a trailing \b can't match after "%"
    # when it's followed by a space or punctuation.
    r"|\breturns? (?:of )?\d+(?:\.\d+)?%"
)
