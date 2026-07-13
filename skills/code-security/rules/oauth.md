---
title: OAuth 2.0 / OIDC Security
impact: HIGH
impactDescription: Authorization code interception, token theft, account takeover, SSRF via redirect_uri
tags: security, oauth, oidc, authentication, authorization, cwe-287, cwe-601, owasp-a07
kind: protocol
---

## OAuth 2.0 / OIDC Security

OAuth 2.0 and OIDC are complex protocols; subtle implementation errors lead to authorization code interception, token theft, open redirects, and account takeover.

Related CWEs: CWE-287 (Improper Authentication), CWE-601 (Open Redirect), CWE-345 (Insufficient Verification of Data Authenticity).

---

### 1. Authorization Code — Single-Use and Bound to Client

**Incorrect:**
```python
# Code not consumed atomically — replay possible
code_record = db.get(code)
if code_record and code_record.client_id == client_id:
    return issue_tokens(code_record.user_id)
# Code still exists in DB after use
```

**Correct:**
```python
# Atomic delete-and-use; duplicate use triggers revocation of issued tokens
code_record = db.pop(code)  # atomic delete
if not code_record or code_record.client_id != client_id:
    revoke_all_tokens_for_grant(code_record)  # RFC 6749 §4.1.2
    raise AuthError("invalid_grant")
if code_record.expires_at < now():
    raise AuthError("invalid_grant")
return issue_tokens(code_record.user_id)
```

---

### 2. Redirect URI — Exact Match Only

**Incorrect:**
```python
# Prefix match — attacker registers https://example.com.evil.com/cb
if redirect_uri.startswith(client.registered_uri):
    redirect(redirect_uri + "?code=" + code)
```

**Correct:**
```python
# Strict equality; query params are ignored per RFC 6749 §3.1.2
from urllib.parse import urlparse

def validate_redirect_uri(client, redirect_uri: str) -> bool:
    parsed = urlparse(redirect_uri)
    # Strip query and fragment before comparison
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return normalized in client.registered_redirect_uris
```

---

### 3. State Parameter — CSRF Prevention

**Incorrect:**
```javascript
// No state parameter — CSRF attack can bind attacker's code to victim's session
const authUrl = `${provider}/authorize?client_id=${CLIENT_ID}&redirect_uri=${REDIRECT_URI}&response_type=code`;
```

**Correct:**
```javascript
// Cryptographically random state, bound to session, verified on callback
const state = crypto.randomBytes(32).toString('hex');
req.session.oauthState = state;
const authUrl = `${provider}/authorize?client_id=${CLIENT_ID}&redirect_uri=${REDIRECT_URI}&response_type=code&state=${state}`;

// On callback:
if (req.query.state !== req.session.oauthState) {
    throw new Error('CSRF detected: state mismatch');
}
delete req.session.oauthState;
```

---

### 4. PKCE for Public Clients

**Incorrect:**
```javascript
// No PKCE — authorization code can be intercepted and exchanged
const authUrl = buildAuthUrl({ response_type: 'code', client_id, redirect_uri });
```

**Correct:**
```javascript
// PKCE (RFC 7636) prevents interception attacks on public clients
const codeVerifier = crypto.randomBytes(32).toString('base64url');
const codeChallenge = crypto.createHash('sha256')
    .update(codeVerifier).digest('base64url');
req.session.codeVerifier = codeVerifier;

const authUrl = buildAuthUrl({
    response_type: 'code',
    client_id,
    redirect_uri,
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
});

// On token exchange — include code_verifier
await exchangeCode({ code, code_verifier: req.session.codeVerifier });
```

---

### 5. ID Token Validation — All Claims Required

**Incorrect:**
```python
# Only verifying signature, missing audience and issuer checks
claims = jwt.decode(id_token, jwks, algorithms=["RS256"])
user_id = claims["sub"]
```

**Correct:**
```python
claims = jwt.decode(
    id_token,
    jwks,
    algorithms=["RS256"],
    audience=CLIENT_ID,           # must match client_id
    issuer=PROVIDER_ISSUER,       # must match provider's issuer claim
    options={"require": ["exp", "iat", "sub", "aud", "iss"]},
)
# Also verify: exp > now(), iat not in the future (clock skew ≤ 5 min),
# nonce matches session nonce (if used)
if claims.get("nonce") != session.pop("nonce", None):
    raise AuthError("nonce mismatch")
user_id = claims["sub"]
```

---

### 6. Access Token Validation (Resource Server)

**Incorrect:**
```python
# Decoding without verifying scope or audience
payload = jwt.decode(token, SECRET, algorithms=["HS256"])
if payload["user_id"]:
    return get_resource()
```

**Correct:**
```python
payload = jwt.decode(
    token,
    SECRET,
    algorithms=["HS256"],
    audience="https://api.example.com",  # resource server's own identifier
)
required_scope = "read:orders"
if required_scope not in payload.get("scope", "").split():
    raise PermissionError("insufficient_scope")
```

---

### 7. Token Endpoint — Client Authentication

**Incorrect:**
```python
# Accepting client_secret in GET query params — logged in access logs
@app.get("/token")
def token(client_id: str, client_secret: str, code: str):
    ...
```

**Correct:**
```python
# POST only; secret via HTTP Basic Auth or POST body (never query params)
@app.post("/token")
def token(request: Request, form: OAuth2TokenForm = Depends()):
    # Extract from Authorization: Basic header or form body
    client_id, client_secret = authenticate_client(request)
    ...
```

---

### 8. Open Redirect via redirect_uri (SSRF / Phishing)

**Incorrect:**
```python
# redirect_uri accepted without validation against allowlist
@app.get("/authorize")
def authorize(redirect_uri: str, ...):
    # ... auth logic ...
    return RedirectResponse(url=f"{redirect_uri}?code={code}")
```

**Correct:**
```python
@app.get("/authorize")
def authorize(client_id: str, redirect_uri: str, ...):
    client = db.get_client(client_id)
    if not validate_redirect_uri(client, redirect_uri):
        raise HTTPException(400, "invalid redirect_uri")
    # ... auth logic ...
    return RedirectResponse(url=f"{redirect_uri}?code={code}&state={state}")
```

---

### 9. Refresh Token Rotation and Reuse Detection

**Incorrect:**
```python
# No rotation — stolen refresh token can be used indefinitely
def refresh(refresh_token: str):
    payload = verify_refresh_token(refresh_token)
    return issue_access_token(payload["sub"])
```

**Correct:**
```python
def refresh(refresh_token: str):
    record = db.pop_refresh_token(refresh_token)  # atomic delete
    if not record:
        # Token already used — possible theft; revoke entire family
        revoke_token_family(refresh_token)
        raise AuthError("invalid_grant")
    new_refresh = issue_refresh_token(record["sub"], family=record["family"])
    new_access = issue_access_token(record["sub"])
    return new_access, new_refresh
```

---

### Quick-Reference Checklist

| Control | Check |
|---------|-------|
| Auth code | Consumed atomically, expires in ≤ 10 min |
| Redirect URI | Exact string match against per-client allowlist |
| State | 32+ bytes random, bound to session, verified on callback |
| PKCE | Required for SPAs and mobile apps (S256 method) |
| ID token | Verify: signature, iss, aud, exp, iat, nonce |
| Access token | Verify: audience = resource server, required scope |
| Client secret | Transmitted only via POST body or Basic Auth header |
| Refresh token | Rotated on every use; reuse triggers family revocation |

**References:**
- [RFC 6749 — The OAuth 2.0 Authorization Framework](https://datatracker.ietf.org/doc/html/rfc6749)
- [RFC 7636 — PKCE](https://datatracker.ietf.org/doc/html/rfc7636)
- [RFC 9700 — OAuth 2.0 Security Best Current Practice](https://datatracker.ietf.org/doc/html/rfc9700)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)

---

## Not a Finding

- `redirect_uri` validated via exact string match against a per-client allowlist — correct; only flag if comparison is prefix/substring
- Auth code flow used for a **confidential client** (server-side app) without PKCE — PKCE is strongly recommended but not strictly required when client secret is securely stored server-side
- `state` parameter absent on endpoints that use **PKCE exclusively** — RFC 7636 PKCE binds the code to the device; state is still best practice but PKCE provides equivalent CSRF protection
- Short-lived access tokens (< 15 min) without refresh tokens on internal CLI tools — acceptable risk for developer tooling
- `iat` claim not verified when `exp` is validated and clock skew tolerance is ≤ 5 min — `iat` check is redundant if `exp` is tight
