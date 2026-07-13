---
title: Celery Task Security
impact: HIGH
impactDescription: Celery tasks process attacker-influenced arguments without the same scrutiny as HTTP handlers, leading to SSRF, command injection, unauthorized actions, and replay attacks
tags: security, celery, async, task-queue, python, ssrf, command-injection, authorization, cwe-284, cwe-918, cwe-78
kind: framework
detect:
  imports: ["celery", "shared_task", "from celery"]
entrypoint_files:
  - "*tasks.py"
  - "*/tasks/*.py"
  - "*/tasks/**/*.py"
entrypoint_markers:
  - "@shared_task"
  - "@app.task"
  - "@celery_app.task"
  - "@periodic_task"
  - ".delay("
  - ".apply_async("
  - "crontab("
triggers:
  - "@shared_task"
  - "@app.task"
  - ".delay("
  - ".apply_async("
  - "requests.get("
  - "subprocess"
  - "os.system("
  - "open("
---

## Celery Task Security

**Tasks are entry points, not just glue.** Their arguments are attacker-influenced whenever the enqueue site passes request-derived input — so audit tasks like HTTP handlers, not like internal functions.

The core mistake is treating a task as "internal" because it runs asynchronously. If `task.delay(user_id=request.user.id, url=request.data["url"])` is called in a view, the task's arguments are fully attacker-controlled.

---

### 1. Tasks That Fetch URLs — SSRF via Queue

**Pattern to find:**

```python
grep -rn "requests.get\|httpx.get\|urllib.request" tasks.py
```

**Incorrect (SSRF — attacker-controlled URL):**

```python
@shared_task
def fetch_webhook_response(callback_url: str, payload: dict):
    # callback_url came from user input at enqueue time
    response = requests.post(callback_url, json=payload)
    return response.json()
```

**Correct (validate URL before HTTP call):**

```python
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"https"}
ALLOWED_HOSTS = {"api.partner.com", "hooks.partner.com"}

@shared_task
def fetch_webhook_response(callback_url: str, payload: dict):
    parsed = urlparse(callback_url)
    if parsed.scheme not in ALLOWED_SCHEMES or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"Disallowed callback URL: {callback_url}")
    response = requests.post(callback_url, json=payload, timeout=10)
    return response.json()
```

---

### 2. Tasks That Run Shell Commands — Command Injection

**Incorrect (command injection):**

```python
@shared_task
def process_file(filename: str):
    # filename from user upload, not sanitized
    os.system(f"convert /uploads/{filename} /processed/{filename}.png")
```

**Correct (avoid shell, use safe API):**

```python
import subprocess
from pathlib import Path

UPLOAD_DIR = Path("/uploads")

@shared_task
def process_file(filename: str):
    # Validate path is within allowed directory
    safe_path = (UPLOAD_DIR / filename).resolve()
    if not str(safe_path).startswith(str(UPLOAD_DIR)):
        raise ValueError("Path traversal detected")
    # Never shell=True, pass list of args
    subprocess.run(
        ["convert", str(safe_path), f"/processed/{safe_path.stem}.png"],
        check=True,
        timeout=30,
    )
```

---

### 3. Authorization Must Be Re-Checked Inside the Task

Tasks do NOT inherit the authentication context from the enqueue call. A task that modifies resources must re-verify the caller has permission to do so.

**Incorrect (authorization assumed from enqueue context):**

```python
# View: enqueues task after checking user is logged in
@login_required
def export_org_data(request):
    export_data.delay(org_id=request.POST["org_id"], user_id=request.user.id)

# Task: never checks if user actually owns org_id
@shared_task
def export_data(org_id: int, user_id: int):
    org = Organization.objects.get(id=org_id)  # IDOR — no ownership check
    return generate_export(org)
```

**Correct (ownership verified inside task):**

```python
@shared_task
def export_data(org_id: int, user_id: int):
    membership = OrgMembership.objects.filter(
        org_id=org_id, user_id=user_id
    ).first()
    if not membership:
        raise PermissionDenied(f"User {user_id} not member of org {org_id}")
    org = Organization.objects.get(id=org_id)
    return generate_export(org)
```

---

### 4. Sensitive Data in Task Arguments — Logged by Workers

Celery serializes task arguments into the broker message. All arguments appear in worker logs, Flower UI, and result backends. Never pass credentials, tokens, or PII as task arguments.

**Incorrect (token in arguments — logged everywhere):**

```python
send_notification.delay(
    user_id=user.id,
    auth_token=user.api_token,  # stored in Redis, logged by worker
    message="Your withdrawal was processed"
)
```

**Correct (look up credentials inside the task):**

```python
@shared_task
def send_notification(user_id: int, message: str):
    user = User.objects.select_related("credentials").get(id=user_id)
    # Fetch the token inside the task — not passed through the queue
    token = user.credentials.notification_token
    push_service.send(token=token, message=message)
```

---

### 5. Replay Attacks — Duplicate Task Execution

Tasks with side effects (payments, emails, state transitions) can be replayed if the broker doesn't deduplicate. A user or attacker who can trigger enqueue (e.g., via a retried HTTP request) may execute the task multiple times.

**Incorrect (no idempotency guard):**

```python
@shared_task
def charge_user(user_id: int, amount: int, order_id: int):
    # If called twice, user is charged twice
    stripe.Charge.create(amount=amount, customer=get_stripe_id(user_id))
    Order.objects.filter(id=order_id).update(status="paid")
```

**Correct (idempotency key prevents double-charge):**

```python
@shared_task
def charge_user(user_id: int, amount: int, order_id: int):
    order = Order.objects.select_for_update().get(id=order_id)
    if order.status == "paid":
        return  # already processed, safe to skip
    stripe.Charge.create(
        amount=amount,
        customer=get_stripe_id(user_id),
        idempotency_key=f"order-{order_id}",
    )
    order.status = "paid"
    order.save()
```

---

### 6. Periodic Tasks — Untrusted Stored State

`crontab()` tasks run without a caller; they read from config or database. If the database row they process was written by a user, the task is still processing attacker-influenced input.

```python
@shared_task
def sync_external_data():
    # Fetches ALL user-configured webhook URLs — attacker may have stored SSRF payload
    for integration in Integration.objects.filter(active=True):
        requests.get(integration.webhook_url)  # SSRF via stored URL
```

**Audit question:** For periodic tasks, trace where the data they consume came from. If any field was set by user input, apply the same input validation as HTTP handlers.

---

## Not a Finding

- Tasks called only from server-side scheduled jobs with hardcoded arguments (no user-supplied values)
- Tasks that only read from database using server-side generated IDs and perform no external HTTP calls
- Internal fanout tasks where arguments are derived entirely from server-generated events

**References:**
- [OWASP SSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
- [Celery Security Best Practices](https://docs.celeryq.dev/en/stable/userguide/security.html)
