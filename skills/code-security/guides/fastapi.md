---
title: FastAPI Code Quality Guide
tags: fastapi, python, dependency-injection, pydantic, async, database, testing
source: https://github.com/awesome-skills/code-review-skill/blob/main/reference/fastapi.md
note: 安全相关内容见 rules/framework-fastapi.md
---

# FastAPI 代码质量指南

依赖注入、Pydantic v2、Async 正确性、数据库会话、测试驱动验证。安全规则见 `rules/framework-fastapi.md`。

---

## 1. 依赖注入 (`Depends`)

### 路由要保持薄，业务逻辑放在依赖或服务中

```python
# ❌ DB 访问、认证、业务规则全部内联在路由里
@app.get("/orders/{order_id}")
async def get_order(order_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
    await conn.close()
    if row is None:
        raise HTTPException(404)
    return dict(row)

# ✅ 路由只声明所需依赖
async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session

@app.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, session: AsyncSession = Depends(get_session)):
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404)
    return order
```

### `yield` 依赖必须清理资源

```python
# ❌ 无清理 — 路由抛出异常时 session 泄漏
async def get_session() -> AsyncSession:
    return SessionLocal()

# ✅ context manager 确保成功和异常都能关闭
async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
```

### 不要每次请求重新创建单例

```python
# ❌ 每次请求创建新的 HTTP client（连接池）
@app.get("/proxy")
async def proxy(client: httpx.AsyncClient = Depends(lambda: httpx.AsyncClient())):
    ...

# ✅ App 生命周期内单例
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient()
    yield
    await app.state.http.aclose()

def get_http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http
```

### 优先使用 `Annotated` 形式

```python
# ⚠️ 旧形式（仍可用）
@app.get("/items")
async def list_items(session: AsyncSession = Depends(get_session)): ...

# ✅ Annotated 形式：定义一次，复用处处
SessionDep = Annotated[AsyncSession, Depends(get_session)]

@app.get("/items")
async def list_items(session: SessionDep): ...
```

### 用依赖验证存在性和权限（每次请求缓存）

```python
# ✅ 小依赖链，valid_post 在一次请求中只解析一次
async def valid_post(post_id: int, session: SessionDep) -> Post:
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404)
    return post

async def owned_post(post: Annotated[Post, Depends(valid_post)], user: CurrentUser) -> Post:
    if post.owner_id != user.id:
        raise HTTPException(status_code=403)
    return post

@app.delete("/posts/{post_id}", status_code=204)
async def delete_post(post: Annotated[Post, Depends(owned_post)], session: SessionDep):
    await session.delete(post)
    await session.commit()
```

---

## 2. Pydantic v2 模型与验证

### 分离输入/输出模型

```python
# ❌ 直接用 ORM 模型作 response_model — hashed_password 泄漏给客户端
@app.post("/users", response_model=UserTable)
async def create_user(user: UserTable): ...

# ✅ 独立的输入/输出 schema
class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: int
    email: EmailStr
    model_config = ConfigDict(from_attributes=True)

@app.post("/users", response_model=UserOut, status_code=201)
async def create_user(payload: UserCreate, session: AsyncSession = Depends(get_session)):
    ...
```

### Create 和 Update 使用独立 schema

```python
# ❌ 同一 schema 用于创建和更新，PATCH 时所有字段变成必填
class ItemSchema(BaseModel):
    name: str
    price: float

# ✅ Update 是 partial
class ItemCreate(BaseModel):
    name: str
    price: float = Field(gt=0)

class ItemUpdate(BaseModel):
    name: str | None = None
    price: float | None = Field(default=None, gt=0)
```

### 在边界验证，不要在 DB 写入后才验证

```python
# ❌ 负数 quantity 到达数据库才发现
@app.post("/cart")
async def add_to_cart(item_id: int, quantity: int):
    await save(item_id, quantity)

# ✅ Pydantic 在 handler 执行前拒绝非法值
class CartLine(BaseModel):
    item_id: int
    quantity: int = Field(gt=0)

@app.post("/cart")
async def add_to_cart(line: CartLine):
    await save(line.item_id, line.quantity)
```

---

## 3. Async 正确性

FastAPI 的吞吐量来自单个事件循环交叉处理并发请求。一次同步调用会阻塞所有在途请求。

### 不要在 `async def` 路由里调用阻塞代码

```python
# ❌ 阻塞所有并发请求
@app.get("/report")
async def report():
    data = requests.get("https://slow-api.example.com").json()  # 阻塞
    time.sleep(2)
    return data

# ✅ 使用原生 async 客户端
@app.get("/report")
async def report(client: httpx.AsyncClient = Depends(get_http)):
    resp = await client.get("https://slow-api.example.com")
    return resp.json()
```

| 同步（阻塞事件循环）| 原生 async 替代 |
|--------------------|----------------|
| `requests` | `httpx.AsyncClient`, `aiohttp` |
| `psycopg2` | `asyncpg`, SQLAlchemy async engine |
| `redis-py` sync | `redis.asyncio` |
| `pymongo` | `motor` |
| `boto3` | `aioboto3` |

### CPU 密集型工作交给 worker 进程

```python
# ❌ CPU 密集任务阻塞事件循环
@app.post("/render")
async def render(doc: Doc):
    return heavy_pdf_render(doc)

# ✅ 入队到 worker 进程
@app.post("/render", status_code=202)
async def render(doc: Doc):
    job = await queue.enqueue(heavy_pdf_render, doc)
    return {"job_id": job.id}
```

### 不要 fire-and-forget 未 await 的协程

```python
# ❌ 协程从未 await，邮件永远不发送
@app.post("/signup")
async def signup(user: UserCreate):
    send_welcome_email(user.email)  # 返回协程对象，被丢弃

# ✅ 用 BackgroundTasks 处理短期 fire-and-forget
@app.post("/signup")
async def signup(user: UserCreate, tasks: BackgroundTasks):
    tasks.add_task(send_welcome_email, user.email)
```

---

## 4. 数据库会话与 N+1

```python
# ❌ 全局共享 session — 并发不安全
session = SessionLocal()

# ✅ 请求级 session 通过依赖注入
@app.get("/items")
async def list_items(session: AsyncSession = Depends(get_session)): ...
```

### 预加载关联避免 N+1

```python
# ❌ N+1：每个 order 查一次 customer
orders = (await session.execute(select(Order))).scalars().all()
return [{"id": o.id, "customer": o.customer.name} for o in orders]

# ✅ 一次查询预加载
stmt = select(Order).options(selectinload(Order.customer))
orders = (await session.execute(stmt)).scalars().all()
```

### 列表接口分页

```python
# ❌ 返回全部行，随表增长退化
@app.get("/users")
async def list_users(session: AsyncSession = Depends(get_session)):
    return (await session.execute(select(User))).scalars().all()

# ✅ 分页 + 上限
@app.get("/users", response_model=list[UserOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(User).limit(limit).offset(offset)
    return (await session.execute(stmt)).scalars().all()
```

### 聚合和 JOIN 在 SQL 中做

```python
# ❌ Python 中循环统计
orders = (await session.execute(select(Order))).scalars().all()
totals: dict[int, float] = {}
for o in orders:
    totals[o.customer_id] = totals.get(o.customer_id, 0) + o.amount

# ✅ 让数据库 GROUP BY + SUM
stmt = select(Order.customer_id, func.sum(Order.amount)).group_by(Order.customer_id)
totals = dict((await session.execute(stmt)).all())
```

---

## 5. 测试驱动验证

"如果你没有看到测试失败，你不知道它测的是正确的东西。"FastAPI 让复现变得廉价：`httpx.AsyncClient` over `ASGITransport` + `app.dependency_overrides` 不需要 mock 内部实现。

### 先写失败的测试复现 bug（RED）

```python
@pytest.mark.asyncio
async def test_user_cannot_delete_another_users_document(session):
    session.add(Document(id=10, owner_id=1, title="Alice's doc"))
    await session.commit()

    app.dependency_overrides[get_current_user] = fake_current_user
    app.dependency_overrides[get_session] = lambda: session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/documents/10", headers={"X-Test-User": "bob"})

    assert resp.status_code == 403  # 先让它失败，确认 bug 存在

    app.dependency_overrides.clear()
```

### 优先使用 `dependency_overrides` 而非 patch

```python
# ❌ patch 内部实现：脆弱，与导入路径耦合
@patch("app.routes.orders.asyncpg.connect")
def test_get_order(mock_connect): ...

# ✅ 覆盖依赖：干净，与实现解耦
app.dependency_overrides[get_session] = lambda: in_memory_session
app.dependency_overrides[get_current_user] = lambda: test_user
# 测试后清理
app.dependency_overrides.clear()
```

### 覆盖失败路径，不只是 happy path

```python
# ❌ 只测成功路径
def test_create_item():
    resp = client.post("/items", json={"name": "x", "price": 5})
    assert resp.status_code == 201

# ✅ 边界和失败路径才是 bug 的聚集地
def test_create_item_rejects_negative_price():
    resp = client.post("/items", json={"name": "x", "price": -5})
    assert resp.status_code == 422

def test_create_item_requires_authentication():
    resp = client_without_auth.post("/items", json={"name": "x", "price": 5})
    assert resp.status_code == 401
```

---

## Review Checklist

### 依赖注入
- [ ] 路由保持薄，DB 和业务规则在 `Depends`/服务中
- [ ] `yield` 依赖通过 context manager 或 `try/finally` 释放资源
- [ ] 单例（HTTP client、连接池）在 `lifespan` 中创建一次
- [ ] 使用 `Annotated[T, Depends(...)]` 形式

### 验证
- [ ] 输入/输出使用独立 Pydantic 模型，ORM 对象不作为 `response_model`
- [ ] Create vs Update 使用独立 schema
- [ ] 约束（`gt`、`le`、`EmailStr`）在边界强制，不在 DB 写入后

### Async
- [ ] `async def` 路由内无阻塞调用
- [ ] 优先使用原生 async SDK
- [ ] CPU 密集型工作交给 worker 进程
- [ ] 无未 await 的协程

### 数据库
- [ ] 请求级 session，无模块级共享 session
- [ ] 关联关系已预加载（`selectinload`/`joinedload`）
- [ ] 列表接口有分页

### 测试
- [ ] bug 在声称发现前先用失败测试复现
- [ ] 使用 `dependency_overrides` 而非 patch 内部
- [ ] 覆盖失败路径（401/403/404/422）
