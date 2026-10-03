# CyanGuard

CyanGuard reviews responses from **Cyan** (an AI assistant for a brokerage) for
SEC and FINRA compliance issues. Each response gets a status (PASS / NEEDS REVIEW /
FAIL), a score, and flags with highlighted excerpts, rule citations, and suggested fixes.

| `APP_MODE` | Cyan (source model)                   | Compliance checker                  | Review storage        | AWS credentials? |
|------------|---------------------------------------|-------------------------------------|-----------------------|------------------|
| `local`    | Synthetic canned responses            | Rule-based (regex) checker          | `data/*.json` files   | No               |
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
| PROMPT_INJECTION | high | OWASP LLM01: Prompt Injection; FINRA 3110 |
| UNAPPROVED_ACTION | high | FINRA 3110; FINRA 2210(b)(1) |
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
    storage.py         # LocalDatabase (JSON files) and DynamoDatabase (one table), split into collections
lambda_handler.py      # Lambda entry point (wraps the app with Mangum)
build_lambda.py        # builds dist/cyanguard-lambda.zip for upload
events/                # sample events for the Lambda console's Test tab
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

### Signing in

The first sign-in creates three demo accounts. They all use the password `cyanguard-demo`,
which the login page shows on purpose for the hackathon demo (override it with `DEMO_PASSWORD`):

| Username | Role | Can do |
|---|---|---|
| `analyst` | Analyst | Run reviews; see only their own |
| `compliance` | Compliance Officer | See every review |
| `admin` | Admin | Everything, including deleting reviews |

Passwords are stored as salted PBKDF2 hashes. Sessions are signed, HttpOnly cookies that
expire after `SESSION_HOURS` (default 8). The demo password only applies when the accounts
are first created; changing it later doesn't update existing accounts.

Endpoints: `GET /health`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`,
`GET /rules`, `POST /cyan/generate`, `GET/POST /reviews`, `GET/DELETE /reviews/{id}`.
Everything except `/health`, login and the static pages requires signing in.

## Run in AWS mode

1. `pip install -r requirements-aws.txt`
2. Configure credentials the usual way (`aws configure` or `AWS_PROFILE`).
3. Create a DynamoDB table named `cyanguard-data` with partition key `collection` (String)
   and sort key `id` (String). All app data (reviews, and later users, sources, ...) lives here.
4. In the Bedrock console, make sure you have access to the model in `BEDROCK_MODEL_ID`
   (and `COMPLIANCE_MODEL_ID`, if you set a separate one).
5. Set `APP_MODE=aws` in `.env`, then run `uvicorn app.main:app --reload` as before.

## Deploy to Lambda

### 1. Build the zip (on your machine)

```bash
python build_lambda.py
```

This creates `dist/cyanguard-lambda.zip` (about 3 MB). It downloads the **Linux**
versions of the packages, because Lambda runs on Linux. Re-run it after every code change.

### 2. Create the function (AWS console, region us-east-1)

1. *Lambda -> Create function -> Author from scratch*: name `cyanguard`,
   runtime **Python 3.12**, architecture **x86_64**.
2. *Code -> Upload from -> .zip file*: upload `dist/cyanguard-lambda.zip`.
3. *Code -> Runtime settings -> Edit*: handler `lambda_handler.handler`.
4. *Configuration -> General configuration -> Edit*: timeout **30 sec**, memory **512 MB**.
5. *Configuration -> Environment variables*:
   - `SESSION_SECRET`: **required**. A long random string that signs login cookies.
     Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   - `DATA_TABLE` only if your table isn't named `cyanguard-data`; `BEDROCK_MODEL_ID` /
     `COMPLIANCE_MODEL_ID` only if you want non-default models.
   `APP_MODE` defaults to `aws` on Lambda, and `AWS_REGION` is set automatically.
6. *Configuration -> Permissions*: click the execution role, then add permissions for
   `dynamodb:Query/GetItem/PutItem/DeleteItem` on the table and `bedrock:InvokeModel`.
7. *Configuration -> Concurrency*: reserved concurrency **2**, to cap cost if the URL leaks.

### 3. Test it

In the *Test* tab, create a test event and paste in the contents of `events/health.json`.
It should return status 200 with `{"status": "ok", "mode": "aws"}`.

Then test sign-in and DynamoDB access with `events/login.json`.
It should return status 200 with `"role": "admin"`. The first run also creates
the demo accounts. An `AccessDeniedException` means step 2.6 is incomplete. To test Bedrock,
sign in through the Function URL and run a compliance check.

### 4. Make it reachable

*Configuration -> Function URL -> Create* with auth type `NONE`. The page itself is public,
but every API call needs a signed-in user, so open the URL and sign in.

### Updating later

Run `python build_lambda.py` again and upload the new zip (step 2.2). Nothing else changes.

Once this gets more involved, consider AWS SAM or CDK to automate these steps.
