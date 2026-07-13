---
title: Go Code Review Guide
tags: go, code-quality, concurrency, error-handling, testing
source: https://github.com/awesome-skills/code-review-skill/blob/main/reference/go.md
---

# Go 代码审查指南

基于 Go 官方指南、Effective Go 和社区最佳实践的代码审查清单。

## 快速审查清单

### 必查项
- [ ] 错误是否正确处理（不忽略、有上下文）
- [ ] goroutine 是否有退出机制（避免泄漏）
- [ ] context 是否正确传递和取消
- [ ] 接收器类型选择是否合理（值/指针）
- [ ] 是否使用 `gofmt` 格式化代码

### 高频问题
- [ ] 循环变量捕获问题（Go < 1.22）
- [ ] nil 检查是否完整
- [ ] map 是否初始化后使用
- [ ] defer 在循环中的使用
- [ ] 变量遮蔽（shadowing）

---

## 1. 错误处理

### 1.1 永远不要忽略错误

```go
// ❌ 错误：忽略错误
result, _ := SomeFunction()

// ✅ 正确：处理错误
result, err := SomeFunction()
if err != nil {
    return fmt.Errorf("some function failed: %w", err)
}
```

### 1.2 错误包装与上下文

```go
// ❌ 错误：丢失上下文
if err != nil {
    return err
}

// ❌ 错误：使用 %v 丢失错误链
if err != nil {
    return fmt.Errorf("failed: %v", err)
}

// ✅ 正确：使用 %w 保留错误链
if err != nil {
    return fmt.Errorf("failed to process user %d: %w", userID, err)
}
```

### 1.3 使用 errors.Is 和 errors.As

```go
// ❌ 错误：直接比较（无法处理包装错误）
if err == sql.ErrNoRows {
    // ...
}

// ✅ 正确：使用 errors.Is（支持错误链）
if errors.Is(err, sql.ErrNoRows) {
    return nil, ErrNotFound
}

// ✅ 正确：使用 errors.As 提取特定类型
var pathErr *os.PathError
if errors.As(err, &pathErr) {
    log.Printf("path error: %s", pathErr.Path)
}
```

### 1.4 自定义错误类型

```go
// ✅ 推荐：定义 sentinel 错误
var (
    ErrNotFound     = errors.New("not found")
    ErrUnauthorized = errors.New("unauthorized")
)

// ✅ 推荐：带上下文的自定义错误
type ValidationError struct {
    Field   string
    Message string
}

func (e *ValidationError) Error() string {
    return fmt.Sprintf("validation error on %s: %s", e.Field, e.Message)
}
```

### 1.5 错误处理只做一次

```go
// ❌ 错误：既记录又返回（重复处理）
if err != nil {
    log.Printf("error: %v", err)
    return err
}

// ✅ 正确：只返回，让调用者决定
if err != nil {
    return fmt.Errorf("operation failed: %w", err)
}
```

---

## 2. 并发与 Goroutine

### 2.1 避免 Goroutine 泄漏

```go
// ❌ 错误：goroutine 永远无法退出
func bad() {
    ch := make(chan int)
    go func() {
        val := <-ch // 永远阻塞，无人发送
        fmt.Println(val)
    }()
}

// ✅ 正确：使用 context 或 done channel
func good(ctx context.Context) {
    ch := make(chan int)
    go func() {
        select {
        case val := <-ch:
            fmt.Println(val)
        case <-ctx.Done():
            return
        }
    }()
}
```

### 2.2 Channel 使用规范

```go
// ❌ 错误：向 nil channel 发送（永久阻塞）
var ch chan int
ch <- 1

// ❌ 错误：向已关闭的 channel 发送（panic）
close(ch)
ch <- 1

// ✅ 正确：发送方关闭 channel
func producer(ch chan<- int) {
    defer close(ch)
    for i := 0; i < 10; i++ {
        ch <- i
    }
}
```

### 2.3 使用 sync.WaitGroup

```go
// ❌ 错误：Add 在 goroutine 内部（竞态条件）
var wg sync.WaitGroup
for i := 0; i < 10; i++ {
    go func() {
        wg.Add(1)
        defer wg.Done()
        work()
    }()
}

// ✅ 正确：Add 在 goroutine 启动前
var wg sync.WaitGroup
for i := 0; i < 10; i++ {
    wg.Add(1)
    go func() {
        defer wg.Done()
        work()
    }()
}
wg.Wait()
```

### 2.4 避免在循环中捕获变量（Go < 1.22）

```go
// ❌ 错误（Go < 1.22）：捕获循环变量
for _, item := range items {
    go func() {
        process(item) // 所有 goroutine 可能使用同一个 item
    }()
}

// ✅ 正确：传递参数
for _, item := range items {
    go func(it Item) {
        process(it)
    }(item)
}
```

### 2.5 Worker Pool 模式

```go
func processWithWorkerPool(ctx context.Context, items []Item, workers int) error {
    jobs := make(chan Item, len(items))
    results := make(chan error, len(items))

    for w := 0; w < workers; w++ {
        go func() {
            for item := range jobs {
                results <- process(item)
            }
        }()
    }

    for _, item := range items {
        jobs <- item
    }
    close(jobs)

    for range items {
        if err := <-results; err != nil {
            return err
        }
    }
    return nil
}
```

---

## 3. Context 使用

### 3.1 Context 作为第一个参数

```go
// ❌ 错误：context 不是第一个参数
func Process(data []byte, ctx context.Context) error

// ❌ 错误：context 存储在 struct 中
type Service struct {
    ctx context.Context
}

// ✅ 正确：context 作为第一个参数，命名为 ctx
func Process(ctx context.Context, data []byte) error
```

### 3.2 始终调用 cancel 函数

```go
// ❌ 错误：未调用 cancel，可能资源泄漏
ctx, cancel := context.WithTimeout(parentCtx, 5*time.Second)

// ✅ 正确：使用 defer 确保调用
ctx, cancel := context.WithTimeout(parentCtx, 5*time.Second)
defer cancel()
```

### 3.3 响应 Context 取消

```go
func LongRunningTask(ctx context.Context) error {
    for {
        select {
        case <-ctx.Done():
            return ctx.Err()
        default:
            if err := doChunk(); err != nil {
                return err
            }
        }
    }
}
```

---

## 4. 接口设计

### 4.1 接受接口，返回结构体

```go
// ❌ 不推荐：接受具体类型
func SaveUser(db *sql.DB, user User) error

// ✅ 推荐：接受接口
type UserStore interface {
    Save(ctx context.Context, user User) error
}

func SaveUser(store UserStore, user User) error

// ✅ 推荐：返回具体类型而非接口
func NewUserService(store UserStore) *UserService
```

### 4.2 在消费者处定义接口，保持小而专注

```go
// ❌ 不推荐：大而全的接口
type Repository interface {
    GetUser(id int) (*User, error)
    CreateUser(u *User) error
    // ... 20+ 方法
}

// ✅ 推荐：在消费者包中定义最小接口
type UserQuerier interface {
    QueryUsers(ctx context.Context, filter Filter) ([]User, error)
}
```

### 4.3 避免空接口滥用，优先泛型（Go 1.18+）

```go
// ❌ 不推荐
func Process(data interface{}) interface{}

// ✅ 推荐：使用泛型
func Process[T any](data T) T
```

---

## 5. 接收器类型

- 需要修改接收器、包含 sync.Mutex、大型结构体 → **指针接收器**
- 小型不可变结构体、基本类型别名、map/chan → **值接收器**
- **一致性原则**：如果有任何方法需要指针接收器，全部使用指针

---

## 6. 性能优化

```go
// ✅ 预分配 Slice
result := make([]int, 0, 10000)

// ✅ 字符串拼接用 strings.Builder
var builder strings.Builder
builder.WriteString(s)
result := builder.String()

// ✅ sync.Pool 复用高频对象
var bufferPool = sync.Pool{
    New: func() interface{} { return new(bytes.Buffer) },
}
```

---

## 7. 测试

```go
// ✅ 表驱动测试
func TestAdd(t *testing.T) {
    tests := []struct {
        name     string
        a, b     int
        expected int
    }{
        {"positive", 1, 2, 3},
        {"with zero", 0, 5, 5},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            if result := Add(tt.a, tt.b); result != tt.expected {
                t.Errorf("got %d, want %d", result, tt.expected)
            }
        })
    }
}

// ✅ t.Helper() 标记辅助函数
func assertEqual(t *testing.T, got, want interface{}) {
    t.Helper()
    if got != want {
        t.Errorf("got %v, want %v", got, want)
    }
}

// ✅ t.Cleanup() 清理资源
func TestWithTempFile(t *testing.T) {
    f, _ := os.CreateTemp("", "test")
    t.Cleanup(func() { os.Remove(f.Name()) })
}
```

---

## 8. 常见陷阱

### Nil Slice vs Empty Slice

```go
var nilSlice []int     // nil — JSON 序列化为 null
emptySlice := []int{}  // 非 nil — JSON 序列化为 []

// 需要空数组 JSON 时显式初始化
if slice == nil {
    slice = []int{}
}
```

### Map 初始化

```go
// ❌ panic: assignment to entry in nil map
var m map[string]int
m["key"] = 1

// ✅ 使用 make 或字面量初始化
m := make(map[string]int)
```

### Defer 在循环中

```go
// ❌ 所有文件在函数结束才关闭
for _, file := range files {
    f, _ := os.Open(file)
    defer f.Close() // 问题！
}

// ✅ 提取到独立函数
for _, file := range files {
    processFile(file)
}
```

### Interface Nil 陷阱

```go
// ❌ 陷阱：interface 包含类型信息，不等于 nil
func returnsError() error {
    var e *MyError = nil
    return e // 返回的 error != nil！
}

// ✅ 显式返回 nil
func returnsError() error {
    var e *MyError = nil
    if e == nil {
        return nil
    }
    return e
}
```

---

## 9. 工具检查

```bash
gofmt -w .           # 格式化（必须）
go vet ./...          # 静态分析
go test -race ./...   # 竞态检测
golangci-lint run     # 综合 lint（errcheck、gosec、staticcheck）
```

---

## 参考资源

- [Effective Go](https://go.dev/doc/effective_go)
- [Go Code Review Comments](https://go.dev/wiki/CodeReviewComments)
- [100 Go Mistakes](https://100go.co/)
- [Uber Go Style Guide](https://github.com/uber-go/guide/blob/master/style.md)
