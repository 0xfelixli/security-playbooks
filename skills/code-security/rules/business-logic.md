---
title: Detect Business Logic Vulnerabilities
impact: CRITICAL
impactDescription: Attackers bypass approval flows, forge state transitions, or exploit process ordering to perform unauthorized actions that pass all technical security checks
tags: security, business-logic, state-machine, approval-bypass, mass-assignment, toctou, cwe-840, cwe-841, owasp-a04
kind: vulnerability
triggers:
  - "**request.data"
  - "**request.POST"
  - "**kwargs"
  - "Object.assign(model"
  - "setattr(obj"
  - "vars(obj).update"
  - "status ="
  - "approved ="
  - "is_admin ="
  - "role ="
---

## Detect Business Logic Vulnerabilities

Business logic vulnerabilities arise when an attacker manipulates the application's intended workflow rather than exploiting a technical flaw. These bugs pass authentication, authorization, and input validation — the flaw is in the design of the process itself.

Common categories:

1. **State machine bypass** — skipping required states or transitions (e.g., moving directly from DRAFT to PUBLISHED without approval)
2. **Approval flow bypass** — submitting to a step that should only be reachable after a prior step completes
3. **Mass assignment** — user-controlled fields overwrite privileged model attributes (status, role, balance)
4. **Trust anchor confusion** — the application trusts a value provided by the caller to validate the caller's own identity (e.g., using the caller-supplied public key to verify the caller's signature)
5. **TOCTOU in business operations** — check-then-act with no lock; concurrent requests all pass the check and each performs the full action (e.g., double-spend)
6. **External call before commit** — irreversible side effect (send money, call external API) happens before the local DB transaction commits; a DB failure leaves state inconsistent

---

### Pattern 1: State Machine Bypass / Approval Flow

**Incorrect (no state guard on publish):**
```python
def publish_article(request, article_id):
    article = get_object_or_404(Article, id=article_id, author=request.user)
    article.status = "PUBLISHED"
    article.save()
    return Response({"status": "published"})
```

**Correct (enforce required prior state):**
```python
PUBLISHABLE_STATES = {"REVIEWED", "APPROVED"}

def publish_article(request, article_id):
    article = get_object_or_404(Article, id=article_id, author=request.user)
    if article.status not in PUBLISHABLE_STATES:
        raise PermissionDenied(f"Cannot publish from state '{article.status}'")
    article.status = "PUBLISHED"
    article.save()
    return Response({"status": "published"})
```

---

### Pattern 2: Mass Assignment

**Incorrect (all user input passed directly to ORM):**
```python
def update_recipe(request, recipe_id):
    recipe = get_object_or_404(Recipe, id=recipe_id)
    recipe = Recipe.model_validate({**recipe.__dict__, **request.data})
    recipe.save()
    return Response(RecipeSerializer(recipe).data)
```

**Correct (explicit allowlist of mutable fields):**
```python
MUTABLE_FIELDS = {"title", "description", "ingredients", "steps"}

def update_recipe(request, recipe_id):
    recipe = get_object_or_404(Recipe, id=recipe_id)
    safe_data = {k: v for k, v in request.data.items() if k in MUTABLE_FIELDS}
    for field, value in safe_data.items():
        setattr(recipe, field, value)
    recipe.save()
    return Response(RecipeSerializer(recipe).data)
```

---

### Pattern 3: Trust Anchor Confusion

An API authenticates callers by verifying a signature, but the public key used to verify the signature is supplied by the caller itself. An attacker generates their own key pair, signs a forged payload, and provides their own public key — verification passes.

**Incorrect (caller supplies the verification key):**
```python
def verify_callback(request):
    biz_api_key = request.headers.get("Biz-Api-Key")
    signature = request.headers.get("Biz-Api-Signature")
    # Public key fetched based on caller-supplied identifier — attacker controls this
    public_key = fetch_public_key(biz_api_key)
    if not verify_signature(public_key, request.body, signature):
        raise AuthenticationFailed()
    process_callback(request.body)
```

**Correct (server-side registry of trusted keys):**
```python
TRUSTED_KEYS = {
    "partner-a": load_public_key("keys/partner-a.pem"),
    "partner-b": load_public_key("keys/partner-b.pem"),
}

def verify_callback(request):
    biz_api_key = request.headers.get("Biz-Api-Key")
    signature = request.headers.get("Biz-Api-Signature")
    public_key = TRUSTED_KEYS.get(biz_api_key)
    if not public_key:
        raise AuthenticationFailed("Unknown caller")
    if not verify_signature(public_key, request.body, signature):
        raise AuthenticationFailed("Invalid signature")
    process_callback(request.body)
```

---

### Pattern 4: TOCTOU (Check-Then-Act Without Lock)

**Incorrect (balance check and debit are separate, no lock):**
```python
def create_order(request):
    amount = Decimal(request.data["amount"])
    account = Account.objects.get(user=request.user)
    if account.balance < amount:
        raise ValidationError("Insufficient balance")
    # Concurrent request also passes the check here
    account.balance -= amount
    account.save()
    Order.objects.create(user=request.user, amount=amount)
```

**Correct (atomic update with conditional deduction):**
```python
from django.db import transaction
from django.db.models import F

def create_order(request):
    amount = Decimal(request.data["amount"])
    with transaction.atomic():
        updated = Account.objects.filter(
            user=request.user, balance__gte=amount
        ).update(balance=F("balance") - amount)
        if not updated:
            raise ValidationError("Insufficient balance")
        Order.objects.create(user=request.user, amount=amount)
```

---

### Pattern 5: External Call Before DB Commit

**Incorrect (irreversible side effect before commit):**
```python
def process_withdrawal(request):
    tx = Transaction.objects.get(id=request.data["tx_id"], user=request.user)
    # External blockchain call — cannot be rolled back
    blockchain_api.broadcast(tx.signed_payload)
    tx.status = "BROADCASTED"
    tx.save()  # If this fails, on-chain action already happened
```

**Correct (commit local state first, then call external):**
```python
from django.db import transaction

def process_withdrawal(request):
    with transaction.atomic():
        tx = Transaction.objects.select_for_update().get(
            id=request.data["tx_id"], user=request.user, status="PENDING"
        )
        tx.status = "SUBMITTING"
        tx.save()
    # External call after local commit; handle failure with retry/status reconciliation
    try:
        blockchain_api.broadcast(tx.signed_payload)
    except Exception:
        Transaction.objects.filter(id=tx.id).update(status="SUBMIT_FAILED")
        raise
    Transaction.objects.filter(id=tx.id).update(status="BROADCASTED")
```

---

### What to Look for in Code Review

- Status or role fields modified without checking the current state
- `**kwargs` or `request.data` passed directly into `model_validate()`, `update()`, or ORM constructors
- Signature verification where the key material comes from the request itself
- Balance/quota checks followed by non-atomic updates (no `select_for_update` or `F()` expression)
- External API calls (payment gateway, blockchain, email send) inside a DB transaction before `commit()`
- "Shadow mode" or "dry run" flags that unconditionally skip enforcement logic

---

**References:**
- CWE-840: Business Logic Errors
- CWE-841: Improper Enforcement of Behavioral Workflow
- CWE-362: Race Condition (TOCTOU)
- [OWASP Testing Guide - Business Logic Testing](https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/10-Business_Logic_Testing/)
- [OWASP Top 10 A04:2021 - Insecure Design](https://owasp.org/Top10/A04_2021-Insecure_Design/)

---

## Not a Finding

- Status field updated via an **explicit state machine** with allowed transition table — transition guard present
- `**kwargs` passed to ORM `update()` where keys come from a **server-side allowlist**, not the request body
- Balance check and deduction in a **single atomic SQL statement** (`UPDATE ... WHERE balance >= amount`) — no TOCTOU window
- External API call **after** DB commit with explicit rollback/compensation logic — CEI pattern handled correctly
- "Dry run" flag controlled by an **admin role claim** in the token — not user-accessible
