---
title: Prevent Memory Safety Vulnerabilities
impact: CRITICAL
impactDescription: Buffer overflows, use-after-free, and integer overflows can lead to arbitrary code execution, privilege escalation, or process crashes
tags: security, memory-safety, buffer-overflow, use-after-free, integer-overflow, format-string, cwe-119, cwe-416, cwe-190, cwe-134
kind: vulnerability
triggers:
  - "strcpy("
  - "strcat("
  - "gets("
  - "sprintf("
  - "scanf("
  - "unsafe.Pointer"
  - "unsafe.Slice"
  - "C.malloc("
  - "free("
  - "printf(user"
  - "fprintf(stderr, user"
---

## Prevent Memory Safety Vulnerabilities

Memory safety vulnerabilities occur when a program accesses memory in unintended ways. They are the root cause of the majority of critical CVEs in native-code software and are directly exploitable to achieve arbitrary code execution.

**Key vulnerability classes:**
- **Buffer overflow** — writing past the end of an allocated buffer (stack or heap), overwriting adjacent memory including return addresses or function pointers
- **Use-after-free (UAF)** — using a pointer after the memory it points to has been freed; the freed region may be reallocated and controlled by an attacker
- **Integer overflow/underflow** — arithmetic wraps around and produces an unexpectedly small value used as a size or index, leading to under-allocation and subsequent overflow
- **Out-of-bounds read** — reading past array bounds leaks adjacent memory (stack canaries, pointers, secrets)
- **Format string injection** — user-controlled format string passed to `printf`-family functions enables arbitrary read/write

**References:** CWE-119 (Improper Restriction of Operations on Memory), CWE-416 (Use After Free), CWE-190 (Integer Overflow), CWE-134 (Uncontrolled Format String)

---

### C — Buffer Overflow (stack)

**Incorrect (unbounded copy into fixed-size buffer):**

```c
#include <string.h>
#include <stdio.h>

void process_input(char *user_input) {
    char buf[64];
    strcpy(buf, user_input);   // no length check — classic stack overflow
    printf("Got: %s\n", buf);
}
```

**Incorrect (gets — unconditionally unsafe):**

```c
void read_line() {
    char buf[128];
    gets(buf);   // never use gets(); it has no length parameter
}
```

**Correct (bounded copy):**

```c
#include <string.h>
#include <stdio.h>

void process_input(const char *user_input) {
    char buf[64];
    strncpy(buf, user_input, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';
    printf("Got: %s\n", buf);
}
```

**Correct (prefer snprintf for building strings):**

```c
void build_message(const char *name) {
    char buf[128];
    snprintf(buf, sizeof(buf), "Hello, %s!", name);
}
```

---

### C — Use-After-Free

**Incorrect (using pointer after free):**

```c
#include <stdlib.h>
#include <string.h>

typedef struct { char data[32]; } Node;

void process(Node *node) {
    free(node);
    // ... later in the same or calling function ...
    memcpy(node->data, "attacker", 8);  // UAF — node is freed
}
```

**Incorrect (double-free):**

```c
void cleanup(char *buf) {
    free(buf);
    // ... error path also calls free(buf) ...
    free(buf);  // double-free corrupts heap metadata
}
```

**Correct (null the pointer immediately after free):**

```c
void cleanup(char **buf) {
    free(*buf);
    *buf = NULL;   // prevents accidental reuse and double-free
}
```

---

### C — Integer Overflow Leading to Buffer Overflow

**Incorrect (size calculation overflows before malloc):**

```c
#include <stdlib.h>
#include <string.h>

void *copy_items(size_t count, size_t item_size) {
    // if count * item_size > SIZE_MAX, result wraps to a small value
    void *buf = malloc(count * item_size);
    return buf;
}
```

**Correct (check for overflow before multiplying):**

```c
#include <stdlib.h>
#include <stdint.h>

void *copy_items(size_t count, size_t item_size) {
    if (item_size != 0 && count > SIZE_MAX / item_size) {
        return NULL;  // would overflow
    }
    return malloc(count * item_size);
}
```

---

### C — Format String Injection

**Incorrect (user input as format string):**

```c
#include <stdio.h>

void log_message(const char *user_input) {
    printf(user_input);          // attacker can pass "%x %x %x" to leak stack
    fprintf(stderr, user_input); // same problem
}
```

**Correct (user input as argument, not format string):**

```c
#include <stdio.h>

void log_message(const char *user_input) {
    printf("%s", user_input);
    fprintf(stderr, "%s\n", user_input);
}
```

---

### C++ — Use-After-Free with Raw Pointers

**Incorrect (raw pointer outlives its owner):**

```cpp
#include <vector>

class Cache {
    std::vector<int> data_;
public:
    const int *get_ptr() { return data_.data(); }
    void resize(size_t n) { data_.resize(n); }  // may reallocate, invalidating old ptr
};

void process(Cache &cache) {
    const int *ptr = cache.get_ptr();
    cache.resize(1000);   // may free old buffer
    int val = *ptr;       // UAF — ptr may now dangle
}
```

**Correct (use index or smart pointer; re-acquire pointer after mutation):**

```cpp
void process(Cache &cache) {
    size_t idx = 0;
    cache.resize(1000);
    int val = cache.get_ptr()[idx];   // re-acquire after resize
}
```

---

### C++ — Prefer Smart Pointers over Raw new/delete

**Incorrect (manual memory management is error-prone):**

```cpp
void process() {
    int *buf = new int[100];
    if (some_condition()) {
        return;           // leak: delete[] never called on this path
    }
    delete[] buf;
}
```

**Correct (RAII — memory freed automatically):**

```cpp
#include <memory>
#include <vector>

void process() {
    auto buf = std::make_unique<int[]>(100);
    // or: std::vector<int> buf(100);
    if (some_condition()) {
        return;  // buf freed automatically by destructor
    }
}
```

---

### Go — Out-of-Bounds Slice Access

Go is memory-safe by default (panics on OOB rather than silently corrupting memory), but `unsafe` bypasses all protections.

**Incorrect (unsafe pointer arithmetic):**

```go
import "unsafe"

func readByte(data []byte, idx int) byte {
    ptr := unsafe.Pointer(&data[0])
    // manual pointer arithmetic — bypasses Go's bounds checks
    return *(*byte)(unsafe.Pointer(uintptr(ptr) + uintptr(idx)))
}
```

**Correct (use normal slice indexing — bounds-checked):**

```go
func readByte(data []byte, idx int) (byte, error) {
    if idx < 0 || idx >= len(data) {
        return 0, fmt.Errorf("index %d out of range [0, %d)", idx, len(data))
    }
    return data[idx], nil
}
```

---

### Rust — Safe vs Unsafe

Rust's ownership model eliminates entire classes of memory safety bugs at compile time. `unsafe` blocks must be audited carefully.

**Incorrect (unnecessary unsafe with raw pointer dereference):**

```rust
fn read_value(ptr: *const u32) -> u32 {
    unsafe { *ptr }   // could be null or dangling
}
```

**Correct (use safe references; caller proves validity via lifetime system):**

```rust
fn read_value(val: &u32) -> u32 {
    *val   // compiler guarantees the reference is valid
}
```

**Correct (validate raw pointers when unsafe is unavoidable):**

```rust
fn read_raw(ptr: *const u32) -> Option<u32> {
    if ptr.is_null() {
        return None;
    }
    Some(unsafe { *ptr })
}
```

---

## Not a Finding

- `unsafe` block in Rust with a `// SAFETY:` comment explaining the invariant and zero user-controlled input reaching raw pointer arithmetic — document but do not flag as a finding
- C `strlen` / `memcpy` on **hardcoded string literals** with known-good lengths — no overflow surface
- Buffer size validated before copy: `if (len > sizeof(buf)) return ERROR;` then `memcpy` — correct pattern
- Rust `unsafe` wrapping a syscall (`libc::getpid()`, `libc::read()`) with no pointer arithmetic and no user-supplied size — low risk, document only
- Memory operations inside a sandboxed WebAssembly module — isolation limits blast radius
