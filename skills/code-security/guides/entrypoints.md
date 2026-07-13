---
title: Attack Surface — Entry Point Enumeration by Tech Stack
impact: HIGH
impactDescription: Unidentified entry points are unchecked attack surface — every missed route is a potential unreviewed injection/auth bypass
tags: security, attack-surface, entrypoints, audit-methodology
kind: reference
---

## Attack Surface — Entry Point Enumeration by Tech Stack

The first step of any security audit is mapping every location where attacker-controlled data enters the system. Missed entry points are missed vulnerabilities. This reference lists the grep patterns and file locations to find entry points across common tech stacks.

**Backend entry points** — where untrusted data enters the server (HTTP routes, queues, cron, CLI)  
**Frontend entry points** — where attacker-controlled data enters the *rendering pipeline* (URL params, API responses, WebSocket messages, postMessage, localStorage)

**Rule:** Treat every entry point as untrusted input until you have traced authentication, authorization, and input validation in its handler.

---

## HTTP Entry Points

### Python — FastAPI

```bash
# Route decorators
grep -rn "@app\.\(get\|post\|put\|delete\|patch\|options\|head\)" .
grep -rn "@router\.\(get\|post\|put\|delete\|patch\)" .

# Router includes (find sub-routers)
grep -rn "include_router\|APIRouter" .

# WebSocket
grep -rn "@app\.websocket\|@router\.websocket" .

# Background tasks as quasi-entry-points
grep -rn "BackgroundTasks\|add_background_task" .
```

Key files: `main.py`, `app.py`, `routers/`, `api/v*/`

### Python — Django / DRF

```bash
# URL patterns
grep -rn "urlpatterns\|path(\|re_path(\|include(" . --include="urls.py"

# Class-based views
grep -rn "class.*\(APIView\|ModelViewSet\|ViewSet\|GenericAPIView\|View\)" .

# Function-based views
grep -rn "@api_view\|@login_required\|def get\|def post\|def put\|def delete" . --include="views.py"

# DRF routers
grep -rn "router\.register\|DefaultRouter\|SimpleRouter" .

# Admin actions (often overlooked)
grep -rn "admin\.site\.register\|ModelAdmin\|@admin\.action" .
```

Key files: `urls.py` (all levels), `views.py`, `viewsets.py`, `serializers.py`

### Python — Flask

```bash
grep -rn "@app\.route\|@bp\.route\|add_url_rule" .
grep -rn "Blueprint\|register_blueprint" .
grep -rn "@app\.websocket\|flask_sock\|flask_socketio" .  # WebSocket
```

### Go — Gin / Echo / Chi / net/http

```bash
# Gin
grep -rn "\.\(GET\|POST\|PUT\|DELETE\|PATCH\|Handle\|Any\)(" . --include="*.go"
grep -rn "gin\.New\|gin\.Default\|r\.Group\|RouterGroup" . --include="*.go"

# Echo
grep -rn "e\.\(GET\|POST\|PUT\|DELETE\|PATCH\)\|e\.Group\|e\.Add" . --include="*.go"

# Chi
grep -rn "r\.Get\|r\.Post\|r\.Put\|r\.Delete\|r\.Route\|chi\.NewRouter" . --include="*.go"

# Standard net/http
grep -rn "http\.HandleFunc\|mux\.Handle\|ServeMux" . --include="*.go"

# gRPC service registrations
grep -rn "Register.*Server\|pb\.Register" . --include="*.go"
```

Key files: `main.go`, `router.go`, `routes.go`, `handler/`, `api/`

### Node.js — Express / NestJS / Koa

```bash
# Express
grep -rn "app\.\(get\|post\|put\|delete\|patch\|use\)(" . --include="*.{js,ts}"
grep -rn "router\.\(get\|post\|put\|delete\|patch\)(" . --include="*.{js,ts}"
grep -rn "express\.Router()" . --include="*.{js,ts}"

# NestJS
grep -rn "@Controller\|@Get\|@Post\|@Put\|@Delete\|@Patch" . --include="*.ts"
grep -rn "@MessagePattern\|@EventPattern\|@GrpcMethod" . --include="*.ts"  # microservices
grep -rn "@WebSocketGateway\|@SubscribeMessage" . --include="*.ts"

# Koa
grep -rn "router\.get\|router\.post\|koaRouter" . --include="*.{js,ts}"
```

### Java — Spring Boot

```bash
grep -rn "@RestController\|@Controller\|@RequestMapping" . --include="*.java"
grep -rn "@GetMapping\|@PostMapping\|@PutMapping\|@DeleteMapping\|@PatchMapping" . --include="*.java"
grep -rn "@RequestParam\|@PathVariable\|@RequestBody" . --include="*.java"  # input sources
```

### Ruby — Rails / Sinatra

```bash
# Rails routes
grep -rn "resources\|get\|post\|put\|delete\|patch\|namespace\|scope" config/routes.rb
grep -rn "def \(index\|show\|create\|update\|destroy\|new\|edit\)" app/controllers/

# Sinatra
grep -rn "get\|post\|put\|delete\|patch" . --include="*.rb"
```

---

## Asynchronous Entry Points

These are frequently missed and often lack the same authentication/authorization as HTTP routes.

### Message Queue Consumers

```bash
# Python — Celery
grep -rn "@app\.task\|@shared_task\|@celery\.task" . --include="*.py"
grep -rn "\.delay(\|\.apply_async(\|\.s(\|chain\|chord\|group" . --include="*.py"

# Python — Kafka (confluent-kafka, aiokafka)
grep -rn "KafkaConsumer\|Consumer(\|\.subscribe(\|\.poll(" . --include="*.py"

# Python — RabbitMQ / Pika
grep -rn "channel\.basic_consume\|channel\.queue_declare\|pika\." . --include="*.py"

# Python — AWS SQS
grep -rn "receive_message\|sqs\.receive\|boto3.*sqs" . --include="*.py"

# Go — Kafka
grep -rn "kafka\.NewConsumer\|sarama\.NewConsumer\|\.ReadMessage\|\.FetchMessage" . --include="*.go"

# Node.js — Bull / BullMQ
grep -rn "Queue\|Worker\|\.process(\|\.add(" . --include="*.{js,ts}"

# Node.js — Kafka (kafkajs)
grep -rn "kafka\.consumer\|\.subscribe(\|\.run(" . --include="*.{js,ts}"
```

**Security focus for queue consumers:** Are messages validated before use? Can an attacker publish to the queue? Is deserialization safe?

### Scheduled / Cron Jobs

```bash
# Python — APScheduler, Celery Beat, django-crontab
grep -rn "@scheduler\.scheduled_job\|add_job\|crontab\|CELERYBEAT_SCHEDULE" . --include="*.py"
grep -rn "@periodic_task\|beat_schedule" . --include="*.py"

# Go — robfig/cron
grep -rn "cron\.New\|c\.AddFunc\|c\.AddJob" . --include="*.go"

# Node.js — node-cron, agenda
grep -rn "cron\.schedule\|agenda\.define\|setInterval\|setTimeout" . --include="*.{js,ts}"

# Java — Spring @Scheduled
grep -rn "@Scheduled\|@EnableScheduling" . --include="*.java"
```

**Security focus:** Does the job consume external data (DB rows, files, API responses)? Is that data sanitized?

### Webhook Receivers

```bash
grep -rn "webhook\|Webhook" . --include="*.{py,go,ts,js,java,rb}"
```

**Security focus:** Is the webhook payload signature verified before processing? SSRF possible if the webhook URL is user-configurable.

---

## WebSocket / Real-time Entry Points

```bash
# Python — websockets, FastAPI WS, Django Channels
grep -rn "websocket\|WebSocket\|ws_connect\|ws_receive\|channel_layer" . --include="*.py"

# Go
grep -rn "Upgrader\|upgrader\.Upgrade\|ws\.ReadMessage\|conn\.ReadMessage" . --include="*.go"

# Node.js — ws, socket.io
grep -rn "new WebSocket\|io\.on\|socket\.on\|wss\.on" . --include="*.{js,ts}"
```

**Security focus:** Is the WebSocket handshake authenticated? Are incoming messages validated? Is there rate limiting?

---

## CLI / Management Entry Points

```bash
# Python — argparse, click, typer
grep -rn "argparse\.ArgumentParser\|@click\.command\|@app\.command\|add_argument" . --include="*.py"

# Python — Django management commands
find . -path "*/management/commands/*.py" -name "*.py"
grep -rn "class.*BaseCommand\|def handle\(self" . --include="*.py"

# Go — cobra, flag
grep -rn "cobra\.Command\|flag\.String\|flag\.Int\|pflag\." . --include="*.go"

# Node.js — commander, yargs
grep -rn "\.command(\|program\.parse\|yargs\." . --include="*.{js,ts}"
```

**Security focus:** CLI commands invoked from scripts/CI may accept input from untrusted pipelines. Check for command injection via arguments.

---

## GraphQL Entry Points

```bash
# Python — Strawberry, Graphene
grep -rn "@strawberry\.type\|@strawberry\.mutation\|graphene\.ObjectType\|graphene\.Mutation" . --include="*.py"
grep -rn "schema = graphene\.\|strawberry\.Schema" . --include="*.py"

# Node.js — Apollo, GraphQL Yoga
grep -rn "typeDefs\|resolvers\|ApolloServer\|createSchema" . --include="*.{js,ts}"
grep -rn "Mutation\|Query\|Subscription" . --include="*.graphql"

# Go — gqlgen
grep -rn "Resolver\|MutationResolver\|QueryResolver" . --include="*.go"
```

**Security focus:** Is query depth/complexity limited? Are mutations authenticated? Can nested queries cause N+1 DoS?

---

## Frontend Entry Points (React / Next.js / Vue / Angular)

Frontend and backend entry points are fundamentally different concepts:
- **Backend:** where attacker data *enters the system*
- **Frontend:** where attacker-controlled data *enters the rendering pipeline*

The same data can flow through multiple frontend entry points before reaching a dangerous sink. Audit both the source (where data comes from) and the sink (where it is rendered or executed).

---

### Source 1 — URL-Derived Input

URL is always attacker-controllable. Any value extracted from it and rendered is a potential DOM XSS.

```bash
# React Router
grep -rn "useParams\|useSearchParams\|useLocation" . --include="*.{tsx,jsx,ts,js}"

# Next.js App Router
grep -rn "searchParams\.\|params\.\|useRouter\(\)\." . --include="*.{tsx,jsx,ts,js}"
grep -rn "props\.params\|props\.searchParams" . --include="*.{tsx,jsx,ts,js}"

# Next.js Pages Router
grep -rn "router\.query\|getServerSideProps\|getStaticProps" . --include="*.{tsx,jsx,ts,js}"

# Raw browser APIs (DOM-based XSS sources)
grep -rn "location\.search\|location\.hash\|location\.href\|document\.referrer\|window\.name" . --include="*.{tsx,jsx,ts,js}"
```

**Security focus:** Is the URL value sanitized before rendering? Is it passed to `dangerouslySetInnerHTML`, `innerHTML`, `href`, or `eval`?

---

### Source 2 — API Response Data Rendered to DOM

The most common frontend XSS vector: backend returns HTML/Markdown/rich text, frontend renders it raw.

```bash
# The primary React XSS sink
grep -rn "dangerouslySetInnerHTML" . --include="*.{tsx,jsx,ts,js}"

# Markdown / rich text renderers with raw HTML enabled
grep -rn "escapeHTML.*false\|sanitize.*false\|allowDangerousHtml\|rehype-raw" . --include="*.{tsx,jsx,ts,js}"
grep -rn "marked\.\|showdown\.\|slack-markdown\|DOMPurify\|sanitizeHtml" . --include="*.{tsx,jsx,ts,js}"

# Direct DOM mutation outside React
grep -rn "\.innerHTML\s*=\|\.outerHTML\s*=\|insertAdjacentHTML\|document\.write" . --include="*.{tsx,jsx,ts,js}"
```

**Security focus:** Is the API response field plain text or can it contain HTML? Is `escapeHTML` explicitly disabled? Is DOMPurify used consistently?

---

### Source 3 — WebSocket / Server-Sent Events

Real-time messages often bypass the same scrutiny as REST responses.

```bash
grep -rn "new WebSocket\|useWebSocket\|WebSocketProvider" . --include="*.{tsx,jsx,ts,js}"
grep -rn "\.onmessage\|addEventListener.*['\"]message['\"]" . --include="*.{tsx,jsx,ts,js}"
grep -rn "EventSource\|useEventSource\|text/event-stream" . --include="*.{tsx,jsx,ts,js}"
```

**Security focus:** Are WebSocket messages treated the same as REST responses (rendered raw)? This was the vector in `cs-chat-message-html-xss` — WS messages fed into `dangerouslySetInnerHTML` without sanitization.

---

### Source 4 — postMessage / Cross-Frame Communication

Messages from other windows/frames arrive without automatic sanitization.

```bash
grep -rn "window\.addEventListener.*message\|self\.addEventListener.*message" . --include="*.{tsx,jsx,ts,js}"
grep -rn "\.postMessage\|window\.parent\." . --include="*.{tsx,jsx,ts,js}"
```

**Security focus:** Is `event.origin` validated before using `event.data`? Can an attacker-controlled iframe send messages? Never trust `event.data` without origin check.

---

### Source 5 — localStorage / sessionStorage / Cookies as Rendering Input

If stored values are reflected back to the DOM, they become persistent XSS vectors.

```bash
grep -rn "localStorage\.getItem\|sessionStorage\.getItem" . --include="*.{tsx,jsx,ts,js}"
grep -rn "document\.cookie" . --include="*.{tsx,jsx,ts,js}"
```

**Security focus:** Is a stored value ever passed to `dangerouslySetInnerHTML` or `innerHTML`? Stored XSS can persist across sessions.

---

### Source 6 — User Form Input Reflected to UI

Input that is displayed back to the user (e.g., previews, search results, chat messages).

```bash
# Find all controlled inputs
grep -rn "onChange\|onInput\|defaultValue\|value={" . --include="*.{tsx,jsx}"

# Look for where the state value is rendered
grep -rn "dangerouslySetInnerHTML.*state\|innerHTML.*input\|innerHTML.*value" . --include="*.{tsx,jsx,ts,js}"
```

---

### Source 7 — Third-Party Scripts and Supply Chain

Loaded scripts run in the same origin and have full DOM access.

```bash
# Script tag insertion
grep -rn "createElement.*script\|document\.body\.append.*script" . --include="*.{tsx,jsx,ts,js}"

# Unpinned CDN dependencies in HTML templates
grep -rn "<script src=\|<link.*href=" . --include="*.{html,tsx,jsx}"

# Next.js Script component
grep -rn "from 'next/script'\|<Script " . --include="*.{tsx,jsx}"
```

**Security focus:** Are third-party scripts loaded over HTTPS with SRI? Are dynamic scripts loaded from user-controlled URLs?

---

### Frontend Dangerous Sinks

| Sink | Risk | Notes |
|------|------|-------|
| `dangerouslySetInnerHTML` | XSS | Always audit — who controls `__html`? |
| `innerHTML =` | XSS | Direct DOM write, bypasses React |
| `eval()` / `new Function()` | Code execution | Any user data in argument = RCE in browser |
| `setTimeout(string)` | Code execution | String form evaluates as JS |
| `href="javascript:"` | XSS | User-controlled href with `javascript:` scheme |
| `src=` with user data | Script injection / SSRF | Dynamic `<script src>`, `<img src onerror>` |
| `window.location = input` | Open redirect | Redirect to attacker-controlled URL |
| `document.write()` | XSS | Overwrites entire document |
| `insertAdjacentHTML()` | XSS | Same as innerHTML |
| `postMessage` without origin check | XSS / data leak | Trust any sender = attacker can send payload |

---

### Route-Level Coverage (React / Next.js SPA)

Frontend routes are also entry points — each route may expose different data and have different auth requirements.

```bash
# React Router routes
grep -rn "<Route\|createBrowserRouter\|createHashRouter" . --include="*.{tsx,jsx,ts,js}"

# Next.js App Router — pages
find . \( -path "*/app/*" -name "page.tsx" -o -name "page.jsx" \) -not -path "*/node_modules/*"

# Next.js Pages Router
find . -path "*/pages/*.{tsx,jsx,ts,js}" -not -path "*/node_modules/*"

# Protected route wrappers
grep -rn "PrivateRoute\|AuthGuard\|RequireAuth\|withAuth\|isAuthenticated" . --include="*.{tsx,jsx,ts,js}"
```

**Security focus:** Are all sensitive routes behind auth guards? Can you access `/admin` or `/settings` by navigating directly without a valid session?

---

### Frontend Coverage Checklist

```
| Component/Route | User Input Source | Render Sink | Auth Required | Status |
|----------------|------------------|-------------|---------------|--------|
| <MessageBubble> | WS message .text | dangerouslySetInnerHTML | session | ⚠️ |
| /search?q= | location.search | <p>{query}</p> | none | ✅ |
| <UserProfile> | API response .bio | innerHTML | session | ❌ |
| /admin/* | — | — | admin role | ❌ |
```

---

After finding entry points, track data flow to these sinks:

| Category | Python | Go | Node.js/TypeScript |
|----------|--------|----|--------------------|
| **DB (raw SQL)** | `cursor.execute(f"...")`  `Model.objects.raw()` `text(f"...")` | `db.Query(fmt.Sprintf(...))` | `` db.query(`...${input}`) `` |
| **Shell exec** | `subprocess(shell=True)` `os.system()` `eval()` | `exec.Command("sh","-c",input)` | `exec(input)` `child_process.exec(input)` |
| **Deserialization** | `pickle.loads()` `yaml.load()` (no SafeLoader) `marshal.loads()` | `json.Unmarshal` with `interface{}` + `encoding/gob` | `JSON.parse` (safe) vs `serialize-javascript` `node-serialize` |
| **File system** | `open(user_path)` `os.path.join(base, user)` | `os.Open(filepath)` | `fs.readFile(userPath)` |
| **HTTP outbound** | `requests.get(user_url)` | `http.Get(userURL)` | `fetch(userURL)` `axios.get(userURL)` |
| **Template** | `render_template_string(user_input)` `Template(user).render()` | `template.HTML(user)` | `res.send(userInput)` (without escaping) |
| **Crypto weak** | `hashlib.md5()` `DES` `ECB mode` | `md5.New()` | `crypto.createHash('md5')` |

---

## Entry Point Coverage Checklist

For each entry point found, record in `api/<module>.md`:

```
| Route/Handler | Method | Auth | Input Source | Sink Type | Status |
|--------------|--------|------|-------------|-----------|--------|
| /api/v2/orders | POST | JWT | JSON body | DB write | ❌ |
| processOrder() | Celery task | None | Queue message | DB write + HTTP out | ❌ |
| /ws/chat/:id | WS | Cookie | WS frame | DB write | ❌ |
```

**Status:** ✅ 已审查（无问题）/ ⚠️ 待深入 / ❌ 未审查

**References:**
- [OWASP Attack Surface Analysis Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Attack_Surface_Analysis_Cheat_Sheet.html)
- [CodeJury attack surface methodology](https://github.com/aiseclabs/codejury)
