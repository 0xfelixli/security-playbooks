# Sections

This file defines all sections, their ordering, impact levels, and descriptions.
The section ID (in parentheses) is the filename prefix used to group rules.

---

## Critical Impact

### 1. SQL Injection (sql-injection)

**Impact:** CRITICAL
**Description:** SQL injection allows attackers to manipulate database queries, leading to data theft, modification, or deletion. OWASP Top 10.

### 2. Command Injection (command-injection)

**Impact:** CRITICAL
**Description:** OS command injection allows attackers to execute arbitrary system commands, leading to full system compromise. CWE-78.

### 3. Cross-Site Scripting (xss)

**Impact:** CRITICAL
**Description:** XSS allows attackers to inject malicious scripts into web pages, leading to session hijacking, defacement, or malware distribution. CWE-79.

### 4. XML External Entity (xxe)

**Impact:** CRITICAL
**Description:** XXE attacks exploit XML parsers to access local files, perform SSRF, or cause denial of service. CWE-611.

### 5. Path Traversal (path-traversal)

**Impact:** CRITICAL
**Description:** Path traversal allows attackers to access files outside intended directories using sequences like "../". CWE-22.

### 6. Insecure Deserialization (insecure-deserialization)

**Impact:** CRITICAL
**Description:** Deserializing untrusted data can lead to remote code execution, DoS, or authentication bypass. CWE-502.

### 7. Code Injection (code-injection)

**Impact:** CRITICAL
**Description:** Code injection (eval, template injection) allows attackers to execute arbitrary code in the application context. CWE-94.

### 8. Hardcoded Secrets (secrets)

**Impact:** CRITICAL
**Description:** Hardcoded credentials, API keys, and tokens in source code lead to unauthorized access when code is exposed. CWE-798.

### 9. Memory Safety (memory-safety)

**Impact:** CRITICAL
**Description:** Memory safety issues (buffer overflow, use-after-free, integer overflow) can lead to code execution or crashes. CWE-119, CWE-416, CWE-190.

### 10. Business Logic (business-logic)

**Impact:** CRITICAL
**Description:** Business logic vulnerabilities — state machine bypass, approval flow bypass, mass assignment, trust anchor confusion, TOCTOU — pass all technical security checks but exploit flawed process design. CWE-840, CWE-841.

---

## High Impact

### 11. Insecure Cryptography (insecure-crypto)

**Impact:** HIGH
**Description:** Weak hashing (MD5, SHA1), weak encryption (DES, RC4), or improper key management compromises data confidentiality. CWE-327.

### 12. Insecure Transport (insecure-transport)

**Impact:** HIGH
**Description:** Cleartext transmission, disabled certificate verification, or weak TLS exposes data in transit. CWE-319.

### 13. Server-Side Request Forgery (ssrf)

**Impact:** HIGH
**Description:** SSRF allows attackers to make requests from the server to internal systems or cloud metadata endpoints. CWE-918.

### 14. JWT Authentication (authentication-jwt)

**Impact:** HIGH
**Description:** JWT vulnerabilities include the "none" algorithm attack, weak secrets, and missing signature verification. CWE-347.

### 15. Cross-Site Request Forgery (csrf)

**Impact:** HIGH
**Description:** CSRF attacks force authenticated users to perform unwanted actions without their knowledge. CWE-352.

### 16. Prototype Pollution (prototype-pollution)

**Impact:** HIGH
**Description:** Prototype pollution in JavaScript can lead to property injection, denial of service, or code execution. CWE-1321.

### 17. Unsafe Functions (unsafe-functions)

**Impact:** HIGH
**Description:** Inherently dangerous functions (gets, strcpy, eval) bypass safety checks and should be avoided. CWE-242.

### 18. Insecure Direct Object Reference (idor)

**Impact:** HIGH
**Description:** IDOR occurs when user-controlled input accesses objects without ownership verification, enabling cross-user, cross-tenant, or cross-service data access. CWE-639, CWE-284.

### 19. API Replay Attack (replay-attack)

**Impact:** HIGH
**Description:** Replay attacks retransmit captured valid requests to repeat critical actions (payments, approvals, state changes) without re-authenticating. CWE-294, CWE-345.

### 20. Terraform AWS Security (terraform-aws)

**Impact:** HIGH
**Description:** AWS infrastructure misconfigurations including public S3 buckets, unencrypted resources, and overly permissive IAM.

### 21. Terraform Azure Security (terraform-azure)

**Impact:** HIGH
**Description:** Azure infrastructure misconfigurations including public endpoints, missing encryption, and insecure network settings.

### 22. Terraform GCP Security (terraform-gcp)

**Impact:** HIGH
**Description:** GCP infrastructure misconfigurations including public resources, disabled logging, and insecure IAM bindings.

### 23. Kubernetes Security (kubernetes)

**Impact:** HIGH
**Description:** Kubernetes misconfigurations including privileged containers, host namespace access, and excessive RBAC permissions.

### 24. Docker Security (docker)

**Impact:** HIGH
**Description:** Docker misconfigurations including running as root, privileged mode, and exposed Docker socket.

### 25. GitHub Actions Security (github-actions)

**Impact:** HIGH
**Description:** GitHub Actions vulnerabilities including script injection, unsafe checkout of PR code, and unpinned actions.

### 26. FastAPI Security (framework-fastapi)

**Impact:** HIGH
**Description:** FastAPI-specific patterns: authentication without authorization (IDOR), sensitive field leakage via response_model, CORS wildcard+credentials, SQL injection in raw queries, blocking I/O inside async routes. CWE-284, CWE-200, CWE-346.

### 27. Django / DRF Security (framework-django)

**Impact:** HIGH
**Description:** Django-specific patterns: mark_safe XSS, CSRF exemption abuse, insecure cookie flags, raw SQL injection, missing ViewSet permission_classes, serializer field exposure, insecure file uploads. CWE-79, CWE-352, CWE-89, CWE-284, CWE-434.

### 28. OAuth 2.0 / OIDC Security (oauth)

**Impact:** HIGH
**Description:** OAuth/OIDC vulnerabilities: authorization code interception, redirect_uri open redirect, missing state/PKCE, incomplete ID token validation, refresh token reuse. CWE-287, CWE-601, CWE-345.

### 29. Celery Task Security (celery)

**Impact:** HIGH
**Description:** Celery tasks process attacker-influenced arguments without the same scrutiny as HTTP handlers — SSRF via callback URLs, command injection, authorization bypass (tasks don't inherit HTTP auth context), sensitive data in broker logs, replay attacks. CWE-284, CWE-918, CWE-78.

---

## Medium Impact

### 30. Regular Expression DoS (regex-dos)

**Impact:** MEDIUM
**Description:** ReDoS attacks exploit inefficient regex patterns to cause CPU exhaustion and denial of service. CWE-1333.

### 31. Race Conditions (race-condition)

**Impact:** MEDIUM
**Description:** TOCTOU race conditions and insecure temporary file creation can lead to privilege escalation. CWE-367. Note: TOCTOU in payment/financial flows is CRITICAL — see business-logic.md.

---

## Low Impact

### 32. Best Practices (best-practice)

**Impact:** LOW
**Description:** Secure coding patterns, deprecated API avoidance, and general recommendations that reduce attack surface.

---

## Rule File Summary

| # | Category | Filename | Impact |
|---|----------|----------|--------|
| 1 | SQL Injection | sql-injection.md | CRITICAL |
| 2 | Command Injection | command-injection.md | CRITICAL |
| 3 | Cross-Site Scripting | xss.md | CRITICAL |
| 4 | XML External Entity | xxe.md | CRITICAL |
| 5 | Path Traversal | path-traversal.md | CRITICAL |
| 6 | Insecure Deserialization | insecure-deserialization.md | CRITICAL |
| 7 | Code Injection | code-injection.md | CRITICAL |
| 8 | Hardcoded Secrets | secrets.md | CRITICAL |
| 9 | Memory Safety | memory-safety.md | CRITICAL |
| 10 | Business Logic | business-logic.md | CRITICAL |
| 11 | Insecure Cryptography | insecure-crypto.md | HIGH |
| 12 | Insecure Transport | insecure-transport.md | HIGH |
| 13 | SSRF | ssrf.md | HIGH |
| 14 | JWT Authentication | authentication-jwt.md | HIGH |
| 15 | CSRF | csrf.md | HIGH |
| 16 | Prototype Pollution | prototype-pollution.md | HIGH |
| 17 | Unsafe Functions | unsafe-functions.md | HIGH |
| 18 | IDOR | idor.md | HIGH |
| 19 | API Replay Attack | replay-attack.md | HIGH |
| 20 | Terraform AWS | terraform-aws.md | HIGH |
| 21 | Terraform Azure | terraform-azure.md | HIGH |
| 22 | Terraform GCP | terraform-gcp.md | HIGH |
| 23 | Kubernetes | kubernetes.md | HIGH |
| 24 | Docker | docker.md | HIGH |
| 25 | GitHub Actions | github-actions.md | HIGH |
| 26 | FastAPI Security | framework-fastapi.md | HIGH |
| 27 | Django / DRF Security | framework-django.md | HIGH |
| 28 | OAuth 2.0 / OIDC | oauth.md | HIGH |
| 29 | Celery Task Security | celery.md | HIGH |
| 30 | Regex DoS | regex-dos.md | MEDIUM |
| 31 | Race Conditions | race-condition.md | MEDIUM |
| 32 | Best Practices | best-practice.md | LOW |
