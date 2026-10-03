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
5. **Route**: every FAIL / NEEDS REVIEW result opens a **compliance case** (see below).

### Demo scenarios

The buttons under the prompt box (Safe Summary, Advisor Review, High-Risk Action, Attack
Simulation) always return a **scripted** Cyan response, in local and AWS mode alike. Real
models' own safeguards usually refuse to write the risky responses a demo needs, so these are
pre-written in `app/services/cyan.py` (`SCENARIOS`). The compliance check on them is real.
Scripted outputs are recorded with the source `cyan-demo-script`. Typed prompts still go to the
model. To add a scenario, add a `Scenario(...)` to `SCENARIOS`; the button appears automatically.

### Compliance cases

Flagged results go to the **Review queue** for a compliance officer:

```
open ──assign──► in review ──approve / reject──► approved / rejected
  │                  │
  └────escalate──────┴──► escalated ──approve / reject (admin only)──► resolved
```

- FAIL results are **high** priority (default 4 hours to resolve); NEEDS REVIEW results are
  **normal** priority (default 24 hours). Admins change both on the Settings page.
- Rejecting, escalating, and reopening require a note. Every action is added to the case's
  audit history, which is never edited.
- Each new case and every escalation creates a **notification**. Notifications are always
  saved to the outbox on the Review queue page. In AWS mode, admins can also turn on **email
  alerts** (Settings page), which are sent through Amazon SNS.

### Reports

The **Reports** page (compliance and admin) covers the last 7, 30, or 90 days:

- Summary tiles: outputs reviewed, pass rate, failures, open and overdue cases, and average time to resolve.
- **Results per day**: a stacked chart of Pass / Needs review / Fail, with a hover tooltip and a table view.
- **Most-triggered rules**, counted once per review.
- **Export CSV**: every review in the period, with its case status. Cells that start with `=`, `+`, `-`, or `@`
  are prefixed with `'` so spreadsheet apps don't run AI output as a formula.
- **Compliance digests**: a dated summary (numbers, top rules, overdue cases) that's saved and sent through
  the notification outbox, and by email when turned on. Generate one any time, or schedule it on AWS (below).

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
  static/              # frontend, plain HTML/CSS/JS (no build step):
                       #   common.js (header, nav by role, api helper) + one script per page:
                       #   index.html/app.js (Analyze), queue, reports, settings, login.html
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
uvicorn app.main:app --reload --reload-dir app
```

`--reload-dir app` keeps the auto-reloader away from `build/` (thousands of files from the Lambda build).

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
`GET /rules`, `POST /cyan/generate`, `GET/POST /reviews`, `GET/DELETE /reviews/{id}`,
`GET /cases`, `POST /reviews/{id}/case`, `GET /users/assignable`, `GET /notifications`,
`GET/PUT /admin/settings`, `GET /reports/summary`, `GET /reports/export.csv`, `GET/POST /reports/digests`.
Everything except `/health`, login and the static pages requires signing in.

## Run in AWS mode

1. `pip install -r requirements-aws.txt`
2. Configure credentials the usual way (`aws configure` or `AWS_PROFILE`).
3. Create a DynamoDB table named `cyanguard-data` with partition key `collection` (String)
   and sort key `id` (String). All app data (reviews, and later users, sources, ...) lives here.
4. In the Bedrock console, make sure you have access to the model in `BEDROCK_MODEL_ID`
   (and `COMPLIANCE_MODEL_ID`, if you set a separate one).
5. Set `APP_MODE=aws` in `.env`, then run `uvicorn app.main:app --reload --reload-dir app` as before.

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
   - `SNS_TOPIC_ARN`: optional. Enables email alerts (see "Email alerts" below).
   - `APP_URL`: optional. Your Function URL (ending in `/`), so scheduled digests can link to the app.
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

### Email alerts (optional, Amazon SNS)

1. Open **Simple Notification Service** (search "SNS" in the console) -> *Topics* -> *Create topic*.
   Type **Standard**, name `cyanguard-alerts`, leave the rest as defaults, *Create topic*.
2. On the topic page, *Create subscription*: protocol **Email**, endpoint = the address that
   should get alerts. Repeat for each person.
3. Each person clicks **Confirm subscription** in the email AWS sends them. Unconfirmed
   addresses get nothing.
4. Copy the topic's **ARN** and add it to the Lambda as `SNS_TOPIC_ARN`.
5. Add `sns:Publish` on that topic ARN to the function's permissions policy.
6. Sign in as `admin`, open **Settings**, turn on **Email alerts**, and save.

Emails come from "AWS Notifications" (no-reply@sns.amazonaws.com). If a send fails, the
alert is still saved in the outbox with the error.

### Scheduled compliance digest (optional, EventBridge Scheduler)

1. Open **Amazon EventBridge** -> *Scheduler* -> *Schedules* -> *Create schedule*.
2. Name it `cyanguard-daily-digest`. Choose **Recurring schedule**, **Cron-based**, e.g.
   `0 9 * * ? *` (9:00 every day), and pick your time zone. Set *Flexible time window* to **Off**.
3. Target: **AWS Lambda - Invoke**, function **CyanGuard**, payload `{"cyanguard_task": "digest"}`.
4. Permissions: **Create new role for this schedule** (it lets the scheduler invoke the function).
5. *Create schedule*. Each run saves a digest (Reports page) and sends it like any other alert.

How many days each scheduled digest covers is set on the Settings page (use 1 for a daily schedule).
To test without waiting, run the Lambda *Test* tab with `events/digest.json`.

### Updating later

Run `python build_lambda.py` again and upload the new zip (step 2.2). Nothing else changes.

Once this gets more involved, consider AWS SAM or CDK to automate these steps.
