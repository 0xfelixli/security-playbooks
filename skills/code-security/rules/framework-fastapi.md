---
title: FastAPI Security Patterns
impact: HIGH
impactDescription: Authentication without authorization enables IDOR; sensitive field leakage exposes credentials; CORS misconfiguration enables cross-origin attacks; blocking async calls create DoS windows
tags: security, fastapi, python, idor, authorization, cors, data-exposure, async, pydantic, cwe-284, cwe-200, cwe-346, owasp-a01, owasp-a02
kind: framework
detect:
  manifest: ["fastapi"]
  imports: ["from fastapi", "import fastapi"]
entrypoint_files:
  - "*main.py"
  - "*/routers/*.py"
  - "*/api/*.py"
  - "*api.py"
  - "*routes.py"
  - "*/endpoints/*.py"
entrypoint_markers:
  - "FastAPI("
  - "APIRouter("
  - "@app.get"
  - "@app.post"
  - "@app.put"
  - "@app.delete"
  - "@app.patch"
  - "@router.get"
  - "@router.post"
  - "Depends("
logic_layers:
  - "*/services/*.py"
  - "*services.py"
  - "*/models/*.py"
  - "*models.py"
  - "*/repositories/*.py"
  - "*/crud/*.py"
  - "*/dao/*.py"
triggers:
  - "Depends(get_current_user)"
  - "Depends(get_current_"
  - "response_model="
  - "allow_origins=[\"*\"]"
  - "allow_credentials=True"
  - "text(f\""
  - "text(\""
  - "connection.execute(f\""
---

## FastAPI Security Patterns

FastAPI-specific security patterns that supplement the generic vulnerability rules. The most common finding: an authentication dependency (`Depends(get_current_user)`) that proves *who* the caller is but never checks *what* they're allowed to touch.

---

### 1. Authentication ≠ Authorization — Always Verify Ownership

The highest-value check in FastAPI reviews. `Depends(get_current_user)` is an authentication gate. It tells you who the caller is. It does **not** tell you they may act on this specific resource.

**Incorrect (authenticated but not authorized — IDOR):**

```python
@app.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    doc = await session.get(Document, doc_id)
    await session.delete(doc)      # any authenticated user can delete anyone's document
    await session.commit()
```

**Correct (ownership checked before mutation):**

```python
@app.delete("/documents/{doc_id}", status_code=204)
async def delete_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Not found")
    if doc.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    await session.delete(doc)
    await session.commit()
```

**Correct (move ownership check into a reusable dependency):**

```python
async def owned_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Document:
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404)
    if doc.owner_id != user.id:
        raise HTTPException(status_code=403)
    return doc

@app.delete("/documents/{doc_id}", status_code=204)
async def delete_document(doc: Document = Depends(owned_document), session: AsyncSession = Depends(get_session)):
    await session.delete(doc)
    await session.commit()
```

---

### 2. Sensitive Field Leakage via `response_model`

When the ORM model is used directly as `response_model`, every field — including `hashed_password`, internal flags, and audit columns — is serialized to the response. FastAPI's `response_model` is a filter: only fields present on the output schema are included.

**Incorrect (ORM model as response — leaks hashed_password):**

```python
@app.post("/users", response_model=UserTable)
async def create_user(user: UserTable):
    ...
```

**Correct (distinct input/output schemas):**

```python
class UserCreate(BaseModel):
    email: EmailStr
    password: str               # input only

class UserOut(BaseModel):
    id: int
    email: EmailStr
    model_config = ConfigDict(from_attributes=True)
    # hashed_password is absent — FastAPI strips it from the response

@app.post("/users", response_model=UserOut, status_code=201)
async def create_user(payload: UserCreate, session: AsyncSession = Depends(get_session)):
    ...
```

Review trigger: any route where `response_model` is a SQLAlchemy/Tortoise/Beanie model class rather than a dedicated Pydantic output schema.

---

### 3. CORS: Wildcard Origin + Credentials

Browsers reject the combination but some HTTP clients (curl, mobile SDKs) do not enforce the restriction. The real risk is that granting `allow_credentials=True` with `allow_origins=["*"]` documents intent to allow any origin to send cookies/tokens — even if browsers block it today, a future relaxation or non-browser client exploits it.

**Incorrect:**

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,   # wildcard + credentials is unsafe
)
```

**Correct:**

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.example.com"],   # explicit allowlist
    allow_credentials=True,
)
```

---

### 4. SQL Injection in Raw Queries

Pydantic validates *shape*, not *SQL safety*. Even with type annotations, string interpolation into `text()` is injectable.

**Incorrect (f-string into text()):**

```python
@app.get("/search")
async def search(email: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        text(f"SELECT * FROM users WHERE email = '{email}'")
    )
    return result.fetchall()
```

**Correct (bound parameter):**

```python
@app.get("/search")
async def search(email: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        text("SELECT * FROM users WHERE email = :email"),
        {"email": email},
    )
    return result.fetchall()
```

---

### 5. Blocking I/O Inside `async def` — DoS Risk

FastAPI runs on a single event loop. One blocking call freezes every in-flight request for its duration — effectively a self-inflicted DoS under load.

**Incorrect (sync HTTP client on the loop):**

```python
@app.get("/report")
async def report():
    data = requests.get("https://slow-api.example.com").json()  # blocks loop
    return data
```

**Incorrect (blocking database driver on the loop):**

```python
@app.get("/users")
async def list_users():
    conn = psycopg2.connect(DATABASE_URL)   # sync driver — blocks loop
    ...
```

**Correct (native-async clients):**

```python
@app.get("/report")
async def report(client: httpx.AsyncClient = Depends(get_http)):
    resp = await client.get("https://slow-api.example.com")
    return resp.json()
```

| Sync (blocks the loop) | Native-async replacement |
|------------------------|--------------------------|
| `requests` | `httpx.AsyncClient`, `aiohttp` |
| `psycopg2` | `asyncpg`, SQLAlchemy async engine |
| `redis-py` sync | `redis.asyncio` |
| `pymongo` | `motor` |
| `boto3` | `aioboto3` |

---

### 6. Error Responses Must Not Leak Internals

**Incorrect (stack trace or SQL in 500 response):**

```python
@app.exception_handler(Exception)
async def generic_handler(request, exc):
    return JSONResponse(status_code=500, content={"detail": str(exc)})
    # str(exc) may contain table names, column names, stack traces
```

**Correct (generic message; log the detail server-side):**

```python
import logging
logger = logging.getLogger(__name__)

@app.exception_handler(Exception)
async def generic_handler(request, exc):
    logger.exception("Unhandled error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
```

---

### 7. Rate Limiting on Auth Endpoints

FastAPI has no built-in rate limiting. Auth endpoints (`/login`, `/token`, `/password-reset`) without rate limiting are open to brute-force and credential stuffing.

**Add `slowapi` or configure an upstream reverse proxy:**

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, credentials: LoginRequest):
    ...
```

---

### Security Checklist

- [ ] Every mutation route verifies ownership/role after authentication — not just that the user is logged in
- [ ] `response_model` is a dedicated output schema, never the ORM model class
- [ ] CORS does not combine `allow_origins=["*"]` with `allow_credentials=True`
- [ ] All raw SQL uses bound parameters — no f-strings or `.format()` into `text()`
- [ ] `async def` routes use only native-async I/O libraries
- [ ] Exception handlers return generic messages; details go to server logs only
- [ ] Auth endpoints have rate limiting
- [ ] Secrets read from environment/config — never hardcoded in route handlers

---

## Not a Finding

- `allow_origins=["*"]` combined with **no credentials** (`allow_credentials=False`) — open CORS is acceptable for public, unauthenticated APIs
- `response_model` is a **Pydantic schema** (not the ORM model) — output is explicitly typed and filtered
- `text()` with bound parameters `text("SELECT * FROM t WHERE id = :id").bindparams(id=pk)` — parameterized, not injectable
- Route returns a 500 with generic message; **details logged server-side** — correct information leakage posture
- `async def` endpoint using `httpx.AsyncClient` — native async, no thread-pool blocking
