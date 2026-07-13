---
title: Prevent Prototype Pollution
impact: HIGH
impactDescription: Attackers inject properties into Object.prototype, corrupting shared state across the application and potentially achieving property injection, denial of service, or remote code execution
tags: security, prototype-pollution, javascript, nodejs, object-merge, cwe-1321, owasp-a08
kind: vulnerability
triggers:
  - "_.merge("
  - "deepmerge("
  - "Object.assign("
  - "extend("
  - "$.extend("
  - "lodash.merge"
  - "merge(target"
  - "__proto__"
  - "constructor.prototype"
---

## Prevent Prototype Pollution

Prototype pollution occurs when an attacker controls input to a function that recursively merges, clones, or assigns properties onto a JavaScript object, and injects properties onto `Object.prototype` or `Function.prototype` via keys such as `__proto__`, `constructor`, or `prototype`.

Since all plain objects inherit from `Object.prototype`, a polluted prototype affects every object in the process — including internal framework objects — for the remainder of that process's lifetime.

**Attack vectors:**
- `merge(target, userControlledObject)` with `__proto__` key
- `set(obj, 'key.__proto__.isAdmin', true)` via dot-path setters
- `JSON.parse` of attacker input followed by recursive merge
- Query-string parsers that produce deeply nested objects (`?__proto__[isAdmin]=true`)

**Impact:**
- **Property injection** — forcing `isAdmin`, `role`, or `debug` to be truthy on all objects
- **DoS** — polluting properties used in hot loops
- **RCE** — in some server-side template engines or `child_process.spawn` option objects that read from prototype

**References:** CWE-1321 (Improperly Controlled Modification of Object Prototype Attributes)

---

### JavaScript/Node.js — Recursive Merge

**Incorrect (recursive merge without key sanitization):**

```javascript
function merge(target, source) {
    for (const key of Object.keys(source)) {
        if (typeof source[key] === 'object' && source[key] !== null) {
            if (!target[key]) target[key] = {};
            merge(target[key], source[key]);   // recurses into __proto__
        } else {
            target[key] = source[key];
        }
    }
    return target;
}

// Attacker payload: JSON.parse('{"__proto__":{"isAdmin":true}}')
merge({}, JSON.parse(userInput));
// Now: ({}).isAdmin === true  for every plain object in the process
```

**Correct (block dangerous keys):**

```javascript
const BLOCKED_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

function merge(target, source) {
    for (const key of Object.keys(source)) {
        if (BLOCKED_KEYS.has(key)) continue;   // skip prototype-polluting keys
        if (typeof source[key] === 'object' && source[key] !== null) {
            if (!target[key]) target[key] = {};
            merge(target[key], source[key]);
        } else {
            target[key] = source[key];
        }
    }
    return target;
}
```

**Correct (use Object.create(null) for accumulator objects that hold untrusted keys):**

```javascript
// Objects with null prototype have no __proto__ chain to pollute
const store = Object.create(null);
store['key'] = value;
```

---

### JavaScript/Node.js — Object.assign with Untrusted Input

**Incorrect (shallow assign from user-controlled object):**

```javascript
app.post('/settings', (req, res) => {
    const defaults = { theme: 'light', lang: 'en' };
    // If req.body contains __proto__: {isAdmin: true}, Object.assign walks it
    const settings = Object.assign({}, defaults, req.body);
    res.json(settings);
});
```

**Correct (whitelist allowed keys):**

```javascript
app.post('/settings', (req, res) => {
    const ALLOWED = ['theme', 'lang'];
    const settings = { theme: 'light', lang: 'en' };
    for (const key of ALLOWED) {
        if (key in req.body) settings[key] = req.body[key];
    }
    res.json(settings);
});
```

---

### JavaScript/Node.js — Dot-path Setters (e.g., lodash.set)

**Incorrect (user-controlled path passed directly to a path setter):**

```javascript
const _ = require('lodash');

app.post('/config', (req, res) => {
    const config = {};
    // req.body.path = '__proto__.isAdmin', req.body.value = 'true'
    _.set(config, req.body.path, req.body.value);   // pollutes Object.prototype
    res.sendStatus(200);
});
```

**Correct (validate path does not traverse prototype chain):**

```javascript
const _ = require('lodash');

function isSafePath(path) {
    const parts = Array.isArray(path) ? path : path.split('.');
    return !parts.some(p => ['__proto__', 'constructor', 'prototype'].includes(p));
}

app.post('/config', (req, res) => {
    if (!isSafePath(req.body.path)) {
        return res.status(400).json({ error: 'Invalid path' });
    }
    const config = {};
    _.set(config, req.body.path, req.body.value);
    res.sendStatus(200);
});
```

---

### JavaScript/Node.js — Query String Parsing

Express's `qs` library (used by `express.urlencoded` and `express.json`) can produce nested objects from query parameters.

**Attacker request:**
```
GET /search?__proto__[isAdmin]=true
```

**Incorrect (using parsed query object as merge source without sanitization):**

```javascript
app.get('/search', (req, res) => {
    const options = {};
    Object.assign(options, req.query);   // req.query may contain __proto__
});
```

**Correct (use allowlist or qs with `allowPrototypes: false`):**

```javascript
const qs = require('qs');

// Parse query string with prototype pollution protection
const params = qs.parse(req.url.split('?')[1], { allowPrototypes: false });
```

---

### TypeScript — Type Safety Does Not Prevent Prototype Pollution

TypeScript's type system operates at compile time; at runtime the object is still a plain JS object. Type annotations do not block `__proto__` injection from JSON or network input.

**Incorrect (trusting type annotation to constrain runtime shape):**

```typescript
interface UserSettings {
    theme: string;
    lang: string;
}

function applySettings(target: UserSettings, source: UserSettings): UserSettings {
    return Object.assign(target, source);   // source may have __proto__ at runtime
}
```

**Correct (validate at runtime before merging):**

```typescript
const ALLOWED_KEYS: Array<keyof UserSettings> = ['theme', 'lang'];

function applySettings(target: UserSettings, source: Record<string, unknown>): UserSettings {
    for (const key of ALLOWED_KEYS) {
        if (key in source) (target as Record<string, unknown>)[key] = source[key];
    }
    return target;
}
```

---

### Detection

Audit any function that:
1. Accepts a plain object from external input (HTTP body, query string, WebSocket message, file)
2. Iterates over its keys with `for...in`, `Object.keys()`, or equivalent
3. Recursively assigns to another object

Search patterns:
```
merge(   deep(   extend(   assign(
_.merge  _.set   _.extend  deepmerge
Object.assign(  for (.*in.*
```

Check that each of these validates or blocks `__proto__`, `constructor`, and `prototype` keys before assignment.

---

## Not a Finding

- `Object.assign({}, source)` where `source` is a **validated schema object** (e.g., Zod/Joi parse result with known keys) — no arbitrary key merging
- Shallow merge that only accesses **explicit property names** (not `for...in` or dynamic key access): `target.name = source.name; target.role = source.role;`
- `JSON.parse()` result directly used — `JSON.parse` creates a fresh object graph; prototype is `Object.prototype` but no `__proto__` key injection unless the key is explicitly accessed
- Libraries using `Object.create(null)` as the merge target — prototype-less object cannot be polluted
- Lodash `_.merge` with **lodash ≥ 4.17.21** applied only to server-internal data (not user-controlled keys) — patched version blocks `__proto__` assignment
