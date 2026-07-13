---
title: Prevent Insecure Direct Object Reference (IDOR)
impact: HIGH
impactDescription: Unauthorized access to other users' data, cross-tenant data leakage, privilege escalation via predictable resource identifiers
tags: security, idor, access-control, authorization, cwe-639, cwe-284, owasp-a01
kind: vulnerability
triggers:
  - "objects.get(id="
  - "objects.get(pk="
  - "findById("
  - "find_by_id("
  - "db.get(id"
  - "db.find(id"
  - "repo.get(id"
  - "c.Param(\"id\""
  - "c.Param('id'"
  - "req.params.id"
  - "params[\"id\"]"
  - "params[:id]"
  - "@PathVariable"
---

## Prevent Insecure Direct Object Reference (IDOR)

IDOR occurs when an application uses user-controlled input to access objects directly without verifying that the authenticated user has permission to access the specific resource. Even a fully authenticated user can be an attacker if they can access another user's or tenant's data by guessing or enumerating identifiers.

Common patterns:
- Fetching a record by ID from the URL without checking ownership (`/api/orders/12345`)
- Cross-tenant access: authenticated user from org A reads data belonging to org B
- Cross-service access: service token A reads resources scoped to service B
- Predictable or sequential IDs that make enumeration trivial

---

### Language: Python (Django)

**Incorrect (no ownership check):**
```python
class BankAccountDetailView(APIView):
    def get(self, request, account_id):
        account = BankAccount.objects.get(id=account_id)
        return Response(BankAccountSerializer(account).data)

    def delete(self, request, account_id):
        account = BankAccount.objects.get(id=account_id)
        account.delete()
        return Response(status=204)
```

**Correct (filter by requesting user's org):**
```python
class BankAccountDetailView(APIView):
    def get(self, request, account_id):
        account = get_object_or_404(BankAccount, id=account_id, org_id=request.user.org_id)
        return Response(BankAccountSerializer(account).data)

    def delete(self, request, account_id):
        account = get_object_or_404(BankAccount, id=account_id, org_id=request.user.org_id)
        account.delete()
        return Response(status=204)
```

---

### Language: JavaScript / Node.js (Express)

**Incorrect (no ownership check):**
```javascript
app.get('/api/documents/:id', async (req, res) => {
    const doc = await Document.findById(req.params.id);
    res.json(doc);
});
```

**Correct (scope to authenticated user):**
```javascript
app.get('/api/documents/:id', async (req, res) => {
    const doc = await Document.findOne({
        _id: req.params.id,
        userId: req.user.id,
    });
    if (!doc) return res.status(403).json({ error: 'Forbidden' });
    res.json(doc);
});
```

---

### Language: Java (Spring Boot)

**Incorrect (no ownership check):**
```java
@GetMapping("/orders/{orderId}")
public Order getOrder(@PathVariable Long orderId) {
    return orderRepository.findById(orderId)
        .orElseThrow(() -> new NotFoundException("Order not found"));
}
```

**Correct (scope to authenticated user):**
```java
@GetMapping("/orders/{orderId}")
public Order getOrder(@PathVariable Long orderId, Principal principal) {
    return orderRepository.findByIdAndUserId(orderId, principal.getName())
        .orElseThrow(() -> new AccessDeniedException("Forbidden"));
}
```

---

### Language: Go

**Incorrect (no ownership check):**
```go
func getDocument(w http.ResponseWriter, r *http.Request) {
    id := chi.URLParam(r, "id")
    doc, err := db.FindDocumentByID(id)
    if err != nil {
        http.Error(w, "not found", 404)
        return
    }
    json.NewEncoder(w).Encode(doc)
}
```

**Correct (scope to authenticated user):**
```go
func getDocument(w http.ResponseWriter, r *http.Request) {
    id := chi.URLParam(r, "id")
    userID := r.Context().Value("userID").(string)
    doc, err := db.FindDocumentByIDAndUser(id, userID)
    if err != nil {
        http.Error(w, "forbidden", 403)
        return
    }
    json.NewEncoder(w).Encode(doc)
}
```

---

### Cross-Service / Cross-Tenant Pattern

A particularly dangerous variant in service-oriented architectures: a service token or API key that is scoped to service A can call endpoints and read resources belonging to service B if the backend does not validate that the caller's service identity matches the resource's owner.

**Incorrect (service token, no service-scope check):**
```python
def get_statement(request, statement_id):
    # Any valid service token can read any statement
    statement = Statement.objects.get(id=statement_id)
    return Response(StatementSerializer(statement).data)
```

**Correct (enforce service-scoped ownership):**
```python
def get_statement(request, statement_id):
    statement = get_object_or_404(
        Statement,
        id=statement_id,
        service_id=request.auth.service_id,  # token must match resource owner
    )
    return Response(StatementSerializer(statement).data)
```

---

**References:**
- CWE-639: Authorization Bypass Through User-Controlled Key
- CWE-284: Improper Access Control
- [OWASP Top 10 A01:2021 - Broken Access Control](https://owasp.org/Top10/A01_2021-Broken_Access_Control/)
- [OWASP IDOR Testing Guide](https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/05-Authorization_Testing/04-Testing_for_Insecure_Direct_Object_References)

---

## Not a Finding

- ID comes from the authenticated session / token (e.g., `request.user.id`) — user cannot supply a different value
- Query already scoped to current user: `.filter(user=request.user, id=pk)` — even if ID is wrong, query returns nothing
- Admin-only endpoint with explicit role check preceding the lookup — intentional broad access
- ID is a non-guessable UUID **and** the endpoint returns no useful data that a random guess would reveal — low exploitability (but note: UUIDs are not a substitute for access control)
- Internal service-to-service call using a machine credential that cannot be forged by end users
