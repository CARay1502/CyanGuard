# CyanGuard

CyanGuard reviews responses from **Cyan** (an AI assistant for a brokerage) for
SEC and FINRA compliance issues. Each response gets a status (PASS / NEEDS REVIEW /
FAIL), a score, and flags with highlighted excerpts, rule citations, and suggested fixes.

| `APP_MODE` | Cyan (source model)                   | Compliance checker                  | Review storage        | AWS credentials? |
|------------|---------------------------------------|-------------------------------------|-----------------------|------------------|
| `local`    | Synthetic canned responses            | Rule-based (regex) checker          | `data/reviews.json`   | No               |
| `aws`      | Bedrock model with a Cyan system prompt | Bedrock model acting as reviewer  | DynamoDB table        | Yes              |

> CyanGuard is a screening aid, not legal advice. Have your compliance team review
> and extend the rule catalog in `app/services/rules.py`.

## How it works

1. **Generate**: `POST /cyan/generate` gets a response from Cyan. You can also paste any LLM output instead.
2. **Check**: `POST /reviews` runs the text through the compliance checker.
   Both checkers use the same rule catalog and return the same flag format.
3. **Score**: `build_report` scores both checkers' results the same way. Each flag costs points
   (high 30, medium 15, low 5). Any high-severity flag means **FAIL**, any other flag means
   **NEEDS REVIEW**, and no flags means **PASS**.
4. **Store**: each review is saved, so it shows up in the Recent reviews list.

### Rules covered

| Rule ID | Severity | Citation |
|---|---|---|
| GUARANTEE | high | FINRA 2150(b); FINRA 2210(d)(1)(B) |
| PROJECTION | high | FINRA 2210(d)(1)(F) |
| SUITABILITY | high | FINRA 2111; SEC Reg BI |
| PII | high | SEC Regulation S-P |
| EXAGGERATED | medium | FINRA 2210(d)(1)(B) |
| PRESSURE | medium | FINRA 2210(d)(1)(A) |
| TESTIMONIAL | medium | FINRA 2210(d)(6); SEC Marketing Rule 206(4)-1 |
| PERSONALIZED_REC | medium | SEC Reg BI |
| MISSING_RISK_DISCLOSURE | medium | FINRA 2210(d)(1)(A) |

To add a rule, append a `Rule(...)` to `RULES` in `app/services/rules.py`. Add `patterns`
for the local checker; the Bedrock checker picks up the new rule from its title and description.

## Project layout

```
app/
  config.py            # reads APP_MODE and other settings from env / .env
  deps.py              # picks local or AWS implementations based on APP_MODE
  main.py              # API routes + serves the frontend
  static/              # frontend: index.html, styles.css, app.js (no build step)
  services/
    cyan.py            # SyntheticCyan (canned samples) and BedrockCyan
    rules.py           # SEC/FINRA rule catalog with citations
    compliance.py      # LocalRuleChecker, BedrockComplianceChecker, build_report
    storage.py         # LocalStorage (JSON file) and DynamoStorage
lambda_handler.py      # Lambda entry point (wraps the app with Mangum)
tests/test_app.py      # runs in local mode, no AWS needed
```

## Run locally (no AWS)

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 for the app, or http://127.0.0.1:8000/docs for interactive API docs.
Run tests with `pytest`.

Endpoints: `GET /health`, `GET /rules`, `POST /cyan/generate`, `GET/POST /reviews`,
`GET/DELETE /reviews/{id}`.

## Run in AWS mode

1. `pip install -r requirements-aws.txt`
2. Configure credentials the usual way (`aws configure` or `AWS_PROFILE`).
3. Create a DynamoDB table named `cyanguard-reviews` with partition key `id` (String).
4. In the Bedrock console, make sure you have access to the model in `BEDROCK_MODEL_ID`
   (and `COMPLIANCE_MODEL_ID`, if you set a separate one).
5. Set `APP_MODE=aws` in `.env`, then run `uvicorn app.main:app --reload` as before.

## Deploy to Lambda

1. Package the code with the AWS dependencies:
   ```bash
   pip install -r requirements-aws.txt -t build/
   ```
   Then copy `app/` and `lambda_handler.py` into `build/` and zip the contents of `build/`.
2. Create a Python 3.12 Lambda function, upload the zip, and set the handler to
   `lambda_handler.handler`. Set the timeout to at least 30 seconds, because Bedrock calls can take several seconds.
3. Set environment variables: `APP_MODE=aws`, `REVIEWS_TABLE`, `BEDROCK_MODEL_ID`,
   and optionally `COMPLIANCE_MODEL_ID`. (`AWS_REGION` is set by Lambda automatically.)
4. Give the function's role permission for `dynamodb:Scan/GetItem/PutItem/DeleteItem`
   on the table and `bedrock:InvokeModel` on the model(s).
5. Add a Function URL or API Gateway trigger to reach it over HTTP.

Once this gets more involved, consider AWS SAM or CDK to automate these steps.
