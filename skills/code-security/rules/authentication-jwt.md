---
title: Secure JWT Authentication
impact: HIGH
impactDescription: Authentication bypass and token forgery
tags: security, authentication, jwt, cwe-287, cwe-347, owasp-a07
kind: vulnerability
triggers:
  - "jwt.decode("
  - "JWT.decode("
  - "verify_signature: False"
  - "verify_signature\":false"
  - "algorithms=[\"none\"]"
  - "algorithms=['none']"
  - "options={\"verify_signature\": False}"
  - "decode(token,"
  - "parseJWT("
  - "decodeJWT("
---

## Secure JWT Authentication

JSON Web Tokens (JWT) are widely used for authentication and authorization. However, improper implementation can lead to serious security vulnerabilities including authentication bypass and token forgery. The most critical JWT vulnerability is decoding tokens without verifying their signatures, which allows attackers to forge tokens with arbitrary claims, impersonate any user, or escalate privileges.

Related CWEs: CWE-287 (Improper Authentication), CWE-345 (Insufficient Verification of Data Authenticity), CWE-347 (Improper Verification of Cryptographic Signature).

**Incorrect (JavaScript jsonwebtoken - decode without verify):**

```javascript
const jwt = require('jsonwebtoken');

function getUserData(token) {
  const decoded = jwt.decode(token, true);
  if (decoded.isAdmin) {
    return getAdminData();
  }
}
```

**Correct (JavaScript jsonwebtoken - use verify which returns decoded payload):**

```javascript
const jwt = require('jsonwebtoken');

function getUserData(token, secretKey) {
  const decoded = jwt.verify(token, secretKey);
  if (decoded.isAdmin) {
    return getAdminData();
  }
}
```

**Incorrect (Python PyJWT - verify_signature disabled):**

```python
import jwt

def get_user_claims(token, key):
    decoded = jwt.decode(token, key, options={"verify_signature": False})
    return decoded
```

**Correct (Python PyJWT - verify_signature enabled):**

```python
import jwt

def get_user_claims(token, key):
    decoded = jwt.decode(token, key, algorithms=["HS256"])
    return decoded
```

**Incorrect (Java auth0 java-jwt - decode without verify):**

```java
import com.auth0.jwt.JWT;
import com.auth0.jwt.interfaces.DecodedJWT;

public class TokenHandler {
    public DecodedJWT getUserClaims(String token) {
        DecodedJWT jwt = JWT.decode(token);
        return jwt;
    }
}
```

**Correct (Java auth0 java-jwt - verify before use):**

```java
import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.interfaces.DecodedJWT;
import com.auth0.jwt.interfaces.JWTVerifier;

public class TokenHandler {
    public DecodedJWT getUserClaims(String token, String secret) {
        Algorithm algorithm = Algorithm.HMAC256(secret);
        JWTVerifier verifier = JWT.require(algorithm)
            .withIssuer("auth0")
            .build();
        DecodedJWT jwt = verifier.verify(token);
        return jwt;
    }
}
```

**References:**
- [OWASP Software and Data Integrity Failures](https://owasp.org/Top10/A08_2021-Software_and_Data_Integrity_Failures)
- [OWASP Cryptographic Failures](https://owasp.org/Top10/A02_2021-Cryptographic_Failures/)
- [CWE-287: Improper Authentication](https://cwe.mitre.org/data/definitions/287)
- [CWE-347: Improper Verification of Cryptographic Signature](https://cwe.mitre.org/data/definitions/347)

---

## Not a Finding

- `jwt.decode()` / `JWT.decode()` used **only for display or logging**, while authorization decisions use a separately verified token — confirm which path gates access
- Algorithm pinned to `HS256`/`RS256` and signature fully verified — `alg: "none"` attack not applicable
- Token already validated upstream by API gateway / reverse proxy that strips and re-asserts claims — only flag if the app also re-decodes without verify
- Read-only endpoints that use the token's `sub` only for logging, not for resource access decisions
