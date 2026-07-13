---
title: Prevent API Replay Attacks
impact: HIGH
impactDescription: Attackers can re-submit captured legitimate requests to repeat actions such as payments, approvals, or state transitions without re-authenticating
tags: security, replay-attack, nonce, idempotency, cwe-294, cwe-345, owasp-a07
kind: vulnerability
triggers:
  - "nonce"
  - "timestamp"
  - "idempotency_key"
  - "idempotency-key"
  - "X-Idempotency-Key"
  - "payment"
  - "withdraw"
  - "transfer"
  - "approve"
  - "sign("
---

## Prevent API Replay Attacks

A replay attack occurs when a previously captured valid request is retransmitted to the server to repeat an action. Even if transport is encrypted (HTTPS), replay is possible if the server does not verify request freshness. Critical operations — payments, fund transfers, approval submissions, signing requests, account mutations — must include replay protection.

**Two complementary defenses:**

1. **Timestamp window** — reject requests where the timestamp is outside an acceptable window (e.g., ±5 minutes). Prevents indefinite replay but does not prevent replay within the window.
2. **Nonce / request ID** — a unique value per request that the server records and rejects on re-use. Combined with a timestamp window, the server only needs to store nonces for the window duration.

---

### Language: Python

**Incorrect (HMAC signature but no timestamp/nonce check):**
```python
import hmac, hashlib

def verify_request(request):
    signature = request.headers.get('X-Signature')
    body = request.body
    expected = hmac.new(SECRET_KEY, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise AuthenticationFailed("Invalid signature")
    # No timestamp check, no nonce check — same request can be replayed forever
    return process(request)
```

**Correct (timestamp window + nonce):**
```python
import hmac, hashlib, time
from django.core.cache import cache

REPLAY_WINDOW_SECONDS = 300

def verify_request(request):
    signature = request.headers.get('X-Signature')
    timestamp = request.headers.get('X-Timestamp')
    nonce = request.headers.get('X-Nonce')

    # 1. Timestamp freshness
    if not timestamp or abs(time.time() - float(timestamp)) > REPLAY_WINDOW_SECONDS:
        raise AuthenticationFailed("Request expired")

    # 2. Nonce uniqueness
    cache_key = f"nonce:{nonce}"
    if cache.get(cache_key):
        raise AuthenticationFailed("Request already processed")
    cache.set(cache_key, True, timeout=REPLAY_WINDOW_SECONDS)

    # 3. Signature covers timestamp + nonce + body
    body = request.body
    signed_payload = f"{timestamp}\n{nonce}\n".encode() + body
    expected = hmac.new(SECRET_KEY, signed_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise AuthenticationFailed("Invalid signature")

    return process(request)
```

---

### Language: JavaScript / Node.js

**Incorrect (no replay protection):**
```javascript
function verifyWebhook(req) {
    const sig = req.headers['x-signature'];
    const expected = crypto.createHmac('sha256', SECRET)
        .update(JSON.stringify(req.body))
        .digest('hex');
    if (sig !== expected) throw new Error('Invalid signature');
    // Replay possible: same payload can be re-sent any number of times
}
```

**Correct (timestamp + nonce):**
```javascript
const usedNonces = new Map(); // In production use Redis with TTL

function verifyWebhook(req) {
    const sig = req.headers['x-signature'];
    const timestamp = req.headers['x-timestamp'];
    const nonce = req.headers['x-nonce'];

    const now = Math.floor(Date.now() / 1000);
    if (Math.abs(now - parseInt(timestamp)) > 300) {
        throw new Error('Request expired');
    }

    if (usedNonces.has(nonce)) {
        throw new Error('Duplicate request');
    }
    usedNonces.set(nonce, Date.now());

    const payload = `${timestamp}\n${nonce}\n${JSON.stringify(req.body)}`;
    const expected = crypto.createHmac('sha256', SECRET).update(payload).digest('hex');
    if (sig !== expected) throw new Error('Invalid signature');
}
```

---

### Language: Java

**Incorrect (no replay protection):**
```java
public boolean verifyRequest(HttpServletRequest request, byte[] body) {
    String signature = request.getHeader("X-Signature");
    String expected = hmacSha256(SECRET_KEY, body);
    return MessageDigest.isEqual(
        expected.getBytes(), signature.getBytes()
    );
    // No timestamp or nonce check
}
```

**Correct (timestamp + nonce via Redis):**
```java
public void verifyRequest(HttpServletRequest request, byte[] body) {
    String signature = request.getHeader("X-Signature");
    String timestamp = request.getHeader("X-Timestamp");
    String nonce = request.getHeader("X-Nonce");

    long ts = Long.parseLong(timestamp);
    if (Math.abs(System.currentTimeMillis() / 1000 - ts) > 300) {
        throw new SecurityException("Request expired");
    }

    String nonceKey = "nonce:" + nonce;
    if (Boolean.TRUE.equals(redisTemplate.hasKey(nonceKey))) {
        throw new SecurityException("Duplicate request");
    }
    redisTemplate.opsForValue().set(nonceKey, "1", Duration.ofSeconds(300));

    String signedPayload = timestamp + "\n" + nonce + "\n" + new String(body);
    String expected = hmacSha256(SECRET_KEY, signedPayload.getBytes());
    if (!MessageDigest.isEqual(expected.getBytes(), signature.getBytes())) {
        throw new SecurityException("Invalid signature");
    }
}
```

---

### Language: Go

**Incorrect (no replay protection):**
```go
func verifyRequest(r *http.Request, body []byte) error {
    sig := r.Header.Get("X-Signature")
    mac := hmac.New(sha256.New, secretKey)
    mac.Write(body)
    expected := hex.EncodeToString(mac.Sum(nil))
    if !hmac.Equal([]byte(expected), []byte(sig)) {
        return errors.New("invalid signature")
    }
    return nil // replay possible
}
```

**Correct (timestamp + nonce):**
```go
func verifyRequest(r *http.Request, body []byte) error {
    sig := r.Header.Get("X-Signature")
    timestamp := r.Header.Get("X-Timestamp")
    nonce := r.Header.Get("X-Nonce")

    ts, _ := strconv.ParseInt(timestamp, 10, 64)
    if diff := time.Now().Unix() - ts; diff > 300 || diff < -300 {
        return errors.New("request expired")
    }

    nonceKey := "nonce:" + nonce
    if exists, _ := redisClient.Exists(ctx, nonceKey).Result(); exists > 0 {
        return errors.New("duplicate request")
    }
    redisClient.Set(ctx, nonceKey, "1", 300*time.Second)

    payload := timestamp + "\n" + nonce + "\n" + string(body)
    mac := hmac.New(sha256.New, secretKey)
    mac.Write([]byte(payload))
    expected := hex.EncodeToString(mac.Sum(nil))
    if !hmac.Equal([]byte(expected), []byte(sig)) {
        return errors.New("invalid signature")
    }
    return nil
}
```

---

### What to Look for in Code Review

- Signature verification present but no timestamp header checked
- Timestamp checked but no nonce / unique request ID
- Nonce stored in process memory (lost on restart) instead of Redis / DB
- Signed payload does not include the timestamp or nonce (attacker can strip headers and reuse signature)
- Replay window is too large (hours/days instead of minutes)

---

**References:**
- CWE-294: Authentication Bypass by Capture-replay
- CWE-345: Insufficient Verification of Data Authenticity
- [OWASP API Security - Broken Authentication](https://owasp.org/www-project-api-security/)
- [OWASP Testing Guide - Testing for Credential Transport over an Encrypted Channel](https://owasp.org/www-project-web-security-testing-guide/)

---

## Not a Finding

- Endpoint is **idempotent by design** and returns the same result on repeated calls (e.g., `GET`, read-only queries) — replay yields no additional impact
- Nonce stored in **Redis/DB with TTL** matching the replay window, and timestamp validated — correct implementation
- Request signed with a **monotonically increasing sequence number** that the server tracks — replay blocked if sequence is not greater than last seen
- Webhook delivery with **event ID deduplication** in a persistent store — equivalent to nonce-based protection
- Internal admin endpoints only callable by machine credentials on a private network — exposure limited, acceptable risk
