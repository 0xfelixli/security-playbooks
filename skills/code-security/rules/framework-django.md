---
title: Django / DRF Security Patterns
impact: HIGH
impactDescription: Django-specific misconfigurations — unsafe template rendering, missing permission classes, insecure cookie flags, raw SQL injection, and unrestricted file uploads — bypass Django's built-in protections
tags: security, django, drf, python, xss, csrf, sql-injection, idor, file-upload, permissions, cookie-security, cwe-79, cwe-352, cwe-89, cwe-284, cwe-434, owasp-a01, owasp-a03, owasp-a05
kind: framework
detect:
  files: ["*urls.py", "manage.py", "*settings.py"]
  manifest: ["django"]
  imports: ["from django", "import django"]
entrypoint_files:
  - "*urls.py"
  - "*views.py"
  - "*viewsets.py"
  - "*/views/*.py"
  - "*serializers.py"
  - "*api.py"
  - "*consumers.py"
entrypoint_markers:
  - "APIView"
  - "ViewSet"
  - "ModelViewSet"
  - "@api_view"
  - "@action"
  - "router.register"
  - "path("
  - "re_path("
  - "as_view("
logic_layers:
  - "*/managers/*.py"
  - "*managers.py"
  - "*/dao/*.py"
  - "*dao.py"
  - "*/services/*.py"
  - "*services.py"
  - "*/models/*.py"
  - "*models.py"
triggers:
  - "mark_safe("
  - "|safe"
  - "format_html("
  - "@csrf_exempt"
  - "csrf_exempt"
  - "permission_classes = []"
  - "authentication_classes = []"
  - ".raw("
  - ".extra(where="
  - "RawSQL("
  - "DEBUG = True"
  - "ALLOWED_HOSTS = [\"*\"]"
  - "ALLOWED_HOSTS = ['*']"
---

## Django / Django REST Framework Security Patterns

Django provides strong defaults (auto-escaping, CSRF middleware, ORM parameterization). The patterns below are how those defaults get accidentally disabled or bypassed.

---

### 1. XSS via `mark_safe()` on User Input

Django templates auto-escape all variables. `mark_safe()` opts a string out of escaping. Passing user-controlled data through `mark_safe()` without escaping first creates a stored or reflected XSS vulnerability.

**Incorrect (user input marked safe without escaping):**

```python
from django.utils.safestring import mark_safe

def render_comment(comment_text):
    # comment_text is user-controlled — any <script> tag executes in the browser
    return mark_safe(comment_text)
```

**Incorrect (mark_safe in template tag):**

```python
@register.simple_tag
def display_name(user):
    return mark_safe(f"<b>{user.display_name}</b>")   # display_name is user-controlled
```

**Correct (escape first, then mark safe):**

```python
from django.utils.html import escape
from django.utils.safestring import mark_safe

@register.simple_tag
def display_name(user):
    safe_name = escape(user.display_name)
    return mark_safe(f"<b>{safe_name}</b>")
```

**Correct (let the template engine do it — prefer this):**

```django
{# In the template — Django escapes automatically #}
<b>{{ user.display_name }}</b>
```

---

### 2. CSRF: Never Exempt API Endpoints That Use Session Auth

`@csrf_exempt` on a view that relies on session cookies removes the only CSRF protection in place. REST endpoints that use token authentication (`Authorization: Bearer`) do not need CSRF tokens — but endpoints accessed via browser sessions do.

**Incorrect (session-auth endpoint exempted from CSRF):**

```python
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def transfer_funds(request):
    # Accessible via browser session — attackers can forge this request
    amount = request.POST["amount"]
    ...
```

**Correct (keep CSRF middleware for session-auth views):**

```python
# Don't use @csrf_exempt. Ensure CsrfViewMiddleware is in MIDDLEWARE.
# For DRF token/JWT auth, DRF's authentication handles CSRF separately;
# don't mix session auth with @csrf_exempt.
def transfer_funds(request):
    amount = request.POST["amount"]
    ...
```

**DRF with SessionAuthentication — ensure CSRF is enforced:**

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        # SessionAuthentication enforces CSRF for non-safe methods
    ],
}
```

---

### 3. Cookie Security Flags

Session cookies without `Secure` and `HttpOnly` are vulnerable to theft over HTTP and via XSS respectively.

**Incorrect (default Django settings — insecure in production):**

```python
# settings.py — Django's defaults allow cookie transmission over HTTP
SESSION_COOKIE_SECURE = False    # default — sends cookie over HTTP
SESSION_COOKIE_HTTPONLY = False  # default — JavaScript can read the cookie
CSRF_COOKIE_SAMESITE = None      # default — no SameSite restriction
```

**Correct (production settings):**

```python
# settings.py
SESSION_COOKIE_SECURE = True      # HTTPS only
SESSION_COOKIE_HTTPONLY = True    # inaccessible to JavaScript
SESSION_COOKIE_SAMESITE = "Lax"   # blocks cross-site POST
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"
```

---

### 4. SQL Injection in Raw Queries

Django's ORM uses parameterized queries by default. Danger arises with `raw()`, `extra()`, and `connection.cursor()` when user input is string-interpolated.

**Incorrect (string interpolation into raw()):**

```python
from django.db import connection

def search_users(query):
    # query is user-controlled
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM auth_user WHERE username = '{query}'")
    # also bad:
    User.objects.raw(f"SELECT * FROM auth_user WHERE username = '{query}'")
```

**Correct (parameterized):**

```python
from django.db import connection

def search_users(query):
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM auth_user WHERE username = %s", [query])

# ORM — always parameterized
User.objects.filter(username=query)
```

---

### 5. ViewSet: Missing `permission_classes` — Any Authenticated User Accesses Any Record

DRF ViewSets without explicit `permission_classes` fall back to `DEFAULT_PERMISSION_CLASSES` from settings. If that default is `AllowAny` or `IsAuthenticated` (without object-level checks), any authenticated user can access any object.

**Incorrect (no permission class — falls back to global default):**

```python
class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()    # returns all orders regardless of owner
    serializer_class = OrderSerializer
    # no permission_classes — relies on whatever DEFAULT_PERMISSION_CLASSES is
```

**Incorrect (authenticated but no object-level check):**

```python
class OrderViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Order.objects.all()    # still returns all users' orders
    serializer_class = OrderSerializer
```

**Correct (filter queryset to current user + explicit permissions):**

```python
from rest_framework.permissions import IsAuthenticated

class OrderViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer

    def get_queryset(self):
        # Scopes the queryset to the requesting user — prevents IDOR
        return Order.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
```

---

### 6. Serializer: `fields = "__all__"` on Sensitive Models

`fields = "__all__"` exposes every column including `password`, `is_staff`, internal audit fields, and future columns added to the model.

**Incorrect:**

```python
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = "__all__"   # includes password hash, is_staff, is_superuser
```

**Correct (explicit allowlist):**

```python
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "date_joined"]

class UserCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["email", "password"]
        extra_kwargs = {"password": {"write_only": True}}  # never serialized in output
```

---

### 7. File Upload: Type Validation and Storage Location

Django's `FileField` and `ImageField` do not validate MIME type by default. Files stored under `MEDIA_ROOT` inside the web root are directly accessible if `DEBUG=True` or if the web server serves them without checks.

**Incorrect (no type validation, stored in web root):**

```python
class UploadView(View):
    def post(self, request):
        uploaded = request.FILES["file"]
        # No MIME/extension check — accepts .php, .py, .exe, etc.
        with open(f"/var/www/uploads/{uploaded.name}", "wb") as f:
            f.write(uploaded.read())
```

**Correct (validate MIME type, limit size, store outside web root):**

```python
import magic   # python-magic
from django.core.exceptions import ValidationError

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "application/pdf"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024   # 10 MB

def validate_upload(file):
    if file.size > MAX_UPLOAD_SIZE:
        raise ValidationError("File too large")
    mime = magic.from_buffer(file.read(2048), mime=True)
    file.seek(0)
    if mime not in ALLOWED_MIME_TYPES:
        raise ValidationError(f"Unsupported file type: {mime}")

class DocumentForm(forms.Form):
    attachment = forms.FileField(validators=[validate_upload])
```

```python
# settings.py — store files outside the web root
MEDIA_ROOT = "/var/private/uploads/"   # not under /var/www/
```

---

### 8. Production Security Checklist

```python
# settings.py — minimum production configuration
DEBUG = False                         # must be False in production
SECRET_KEY = os.environ["SECRET_KEY"] # from environment, never hardcoded
ALLOWED_HOSTS = ["app.example.com"]   # never ["*"] in production

SECURE_SSL_REDIRECT = True            # redirect HTTP → HTTPS
SECURE_HSTS_SECONDS = 31536000        # 1 year HSTS
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True

DATABASES = {
    "default": {
        ...
        "OPTIONS": {"sslmode": "require"},  # enforce DB SSL
    }
}

CORS_ALLOWED_ORIGINS = ["https://app.example.com"]  # never CORS_ALLOW_ALL_ORIGINS = True in prod
```

---

### Security Checklist

- [ ] `mark_safe()` never called on user-controlled input without prior `escape()`
- [ ] `@csrf_exempt` not applied to endpoints that rely on session cookies
- [ ] `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `CSRF_COOKIE_SECURE` are `True` in production
- [ ] Raw SQL (`cursor.execute`, `raw()`, `extra()`) uses `%s` / named params — no f-strings
- [ ] ViewSets have explicit `permission_classes` and `get_queryset()` filters to current user
- [ ] Serializers use an explicit field allowlist — not `fields = "__all__"`
- [ ] Write-only fields (`password`, tokens) marked `write_only=True` in serializers
- [ ] File uploads validate MIME type and size; stored outside the web root
- [ ] `DEBUG = False` and `SECRET_KEY` from environment in production

---

## Not a Finding

- `mark_safe()` called on content **already HTML-escaped** via `escape()` or `conditional_escape()` — safe pattern
- `@csrf_exempt` on an endpoint that uses **Bearer token auth only** (no session cookie) — CSRF requires ambient credentials; JWT in `Authorization` header is not auto-sent by browsers cross-origin
- `fields = "__all__"` in a **read-only serializer** (`ReadOnlyModelSerializer`) used only for output — mass assignment is an input risk, not output
- `cursor.execute(sql, params)` with `%s` bound parameters — parameterized, not injectable
- `CORS_ALLOW_ALL_ORIGINS = True` on a **public API** that uses token auth and no session cookies — no CSRF risk; CORS relaxation only matters for cookie-based auth
