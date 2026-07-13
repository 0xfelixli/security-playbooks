---
title: TypeScript Code Review Guide
tags: typescript, code-quality, type-safety, generics, async, immutability
source: https://github.com/awesome-skills/code-review-skill/blob/main/reference/typescript.md
---

# TypeScript 代码审查指南

覆盖类型系统、泛型、条件类型、strict 模式、async/await 模式等核心主题。

---

## 1. 类型安全基础

### 避免使用 any

```typescript
// ❌ any 绕过类型检查
function processData(data: any) {
  return data.value;
}

// ✅ 使用明确类型
interface DataPayload { value: string; }
function processData(data: DataPayload) { return data.value; }

// ✅ 未知类型用 unknown + 类型守卫
function processUnknown(data: unknown) {
  if (typeof data === 'object' && data !== null && 'value' in data) {
    return (data as { value: string }).value;
  }
  throw new Error('Invalid data');
}
```

### 类型收窄

```typescript
// ❌ 不安全的类型断言
function getLength(value: string | string[]) {
  return (value as string[]).length;  // string 时出错
}

// ✅ 使用类型守卫
function getLength(value: string | string[]): number {
  if (Array.isArray(value)) return value.length;
  return value.length;
}

// ✅ 使用 in 操作符
interface Dog { bark(): void }
interface Cat { meow(): void }

function speak(animal: Dog | Cat) {
  if ('bark' in animal) animal.bark();
  else animal.meow();
}
```

### 字面量类型与 as const

```typescript
// ❌ method 类型是 string，无法传给需要 'GET' | 'POST' 的函数
const config = { endpoint: '/api', method: 'GET' };

// ✅ as const 获得字面量类型
const config = { endpoint: '/api', method: 'GET' } as const;
// config.method 类型是 'GET'
```

---

## 2. 泛型模式

```typescript
// ✅ 基础泛型消除重复
function getFirst<T>(arr: T[]): T | undefined { return arr[0]; }

// ✅ keyof 约束
function getProperty<T, K extends keyof T>(obj: T, key: K): T[K] {
  return obj[key];
}

// ✅ 泛型默认值
interface ApiResponse<T = unknown> {
  data: T;
  status: number;
}

// ✅ 内置工具类型
type PartialUser = Partial<User>;
type ReadonlyUser = Readonly<User>;
type NameOnly = Pick<User, 'name'>;
type WithoutId = Omit<User, 'id'>;
```

---

## 3. 高级类型

### 条件类型

```typescript
type IsString<T> = T extends string ? true : false;
type ElementType<T> = T extends (infer U)[] ? U : never;
```

### 映射类型

```typescript
type Nullable<T> = { [K in keyof T]: T[K] | null };

// 添加 getter 前缀
type Getters<T> = {
  [K in keyof T as `get${Capitalize<string & K>}`]: () => T[K];
};
```

### 模板字面量类型

```typescript
type EventName = 'click' | 'focus' | 'blur';
type HandlerName = `on${Capitalize<EventName>}`;
// 'onClick' | 'onFocus' | 'onBlur'
```

### Discriminated Unions

```typescript
// ✅ 判别联合类型，模式匹配安全
type Result<T, E> =
  | { success: true; data: T }
  | { success: false; error: E };

function handleResult(result: Result<User, Error>) {
  if (result.success) {
    console.log(result.data.name);   // TypeScript 保证 data 存在
  } else {
    console.log(result.error.message);
  }
}
```

---

## 4. Strict 模式配置

```json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "useUnknownInCatchVariables": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitReturns": true,
    "exactOptionalPropertyTypes": true
  }
}
```

```typescript
// noUncheckedIndexedAccess 的影响
const arr = [1, 2, 3];
const first = arr[0];  // 类型是 number | undefined

// ❌ 直接使用
first.toFixed(2);  // Error

// ✅ 先检查
if (first !== undefined) first.toFixed(2);
```

---

## 5. 异步处理

```typescript
// ✅ 正确处理 HTTP 错误
async function fetchUser(id: string): Promise<User> {
  try {
    const response = await fetch(`/api/users/${id}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`Failed to fetch user: ${error.message}`);
    }
    throw error;
  }
}

// ✅ Promise.allSettled 收集所有结果（不因单个失败终止）
async function fetchAllUsers(ids: string[]) {
  const results = await Promise.allSettled(ids.map(fetchUser));
  const users: User[] = [];
  const errors: Error[] = [];
  for (const result of results) {
    if (result.status === 'fulfilled') users.push(result.value);
    else errors.push(result.reason);
  }
  return { users, errors };
}

// ✅ AbortController 处理竞态条件
useEffect(() => {
  const controller = new AbortController();
  fetch(`/api/search?q=${query}`, { signal: controller.signal })
    .then(r => r.json())
    .then(setResults)
    .catch(e => { if (e.name !== 'AbortError') throw e; });
  return () => controller.abort();
}, [query]);
```

---

## 6. 不可变性

```typescript
// ❌ 函数修改了参数
function processUsers(users: User[]) {
  users.sort(/* ... */);  // 修改原数组！
  return users;
}

// ✅ readonly 防止修改
function processUsers(users: readonly User[]): User[] {
  return [...users].sort(/* ... */);
}
```

---

## 7. ESLint 规则

```javascript
// .eslintrc.js
module.exports = {
  extends: [
    'plugin:@typescript-eslint/recommended',
    'plugin:@typescript-eslint/recommended-requiring-type-checking',
  ],
  rules: {
    '@typescript-eslint/no-explicit-any': 'error',
    '@typescript-eslint/no-floating-promises': 'error',   // 不允许未处理的 Promise
    '@typescript-eslint/no-misused-promises': 'error',
    '@typescript-eslint/consistent-type-imports': 'error',
    '@typescript-eslint/prefer-nullish-coalescing': 'error',
  },
};
```

```typescript
// ❌ no-floating-promises
save();  // 未处理的 Promise

// ✅ 显式处理
await save();
void save();   // 明确忽略

// ❌ forEach 中使用 async
items.forEach(async (item) => { await processItem(item); });

// ✅ for...of 或 Promise.all
for (const item of items) await processItem(item);
await Promise.all(items.map(processItem));
```

---

## Review Checklist

### 类型系统
- [ ] 没有使用 `any`（用 `unknown` + 类型守卫代替）
- [ ] 联合类型有正确的类型收窄
- [ ] 善用工具类型（Partial、Pick、Omit 等）

### Strict 模式
- [ ] tsconfig.json 启用了 `strict: true`
- [ ] 启用了 `noUncheckedIndexedAccess`
- [ ] 没有使用 `@ts-ignore`（改用 `@ts-expect-error`）

### 异步代码
- [ ] async 函数有错误处理
- [ ] 没有 floating promises（未处理的 Promise）
- [ ] 并发请求使用 Promise.all 或 Promise.allSettled
- [ ] 竞态条件使用 AbortController 处理

### 不可变性
- [ ] 不直接修改函数参数
- [ ] 考虑使用 `readonly` 修饰符

### ESLint
- [ ] 使用 `@typescript-eslint/recommended`
- [ ] 无 ESLint 警告或错误

---

## 安全注意事项：类型系统不保护什么

> 这是 TypeScript 项目最容易产生安全误判的地方——开发者看到类型声明就以为输入已被验证。

### 类型在运行时被擦除

TypeScript 的类型信息只在编译期存在。HTTP 请求、JSON 解析、外部 API 响应到达时，没有任何运行时机制保证它们符合声明的类型。

```typescript
// ❌ 类型声明 ≠ 运行时验证
interface CreateOrderBody {
  amount: number;   // 用户可以发送字符串、负数、注入payload
  userId: string;
}
app.post('/orders', async (req, res) => {
  const body = req.body as CreateOrderBody; // `as` 是欺骗自己，不是保护
  await db.query(`INSERT INTO orders VALUES (${body.amount})`); // SQL 注入
});
```

```typescript
// ✅ 使用 zod/class-validator 做运行时验证
import { z } from 'zod';
const CreateOrderSchema = z.object({
  amount: z.number().int().positive().max(1_000_000),
  userId: z.string().uuid(),
});
app.post('/orders', async (req, res) => {
  const body = CreateOrderSchema.parse(req.body); // 失败则抛出异常
  await db.query('INSERT INTO orders VALUES ($1)', [body.amount]);
});
```

### `as` 类型断言隐藏不可信数据

`as` 只是告诉编译器"相信我"，不做任何验证。在安全审计中，`as SomeType` 后面跟着对字段的使用，需要追溯该值的来源。

```typescript
// ❌ as 断言让危险数据看起来安全
const user = jwt.decode(token) as UserPayload; // decode 不验证签名！
if (user.isAdmin) { ... }  // 攻击者可伪造

// ✅ 验证签名后再使用
const user = jwt.verify(token, SECRET) as UserPayload;
```

### `JSON.parse` 返回 `any`

`JSON.parse` 的返回类型是 `any`，意味着从该值派生的所有内容都失去类型检查保护。

```typescript
// ❌ 解析外部 JSON 后直接使用
const data = JSON.parse(rawBody);       // 返回 any
const id = data.userId;                  // any，无类型保护
await db.find(id);                       // 潜在注入

// ✅ 用 schema 验证解析结果
const data = ResponseSchema.parse(JSON.parse(rawBody));
```

### NestJS / class-validator 的批量赋值风险

NestJS 的 `@Body()` 不加 `ValidationPipe` 时，接受任意字段并绑定到 DTO。

```typescript
// ❌ 没有 ValidationPipe — 客户端可以发送 isAdmin: true
@Post('/profile')
async updateProfile(@Body() dto: UpdateProfileDto) {
  await this.userService.update(userId, dto); // dto 未经过滤
}

// ✅ 全局启用 ValidationPipe + whitelist
app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true }));
```

### 审计时的关键搜索模式

```bash
# 找所有 as 断言中使用外部数据的地方
grep -rn "req\.body as\|req\.params as\|JSON\.parse" . --include="*.ts"

# 找 jwt.decode（不验证签名）vs jwt.verify
grep -rn "jwt\.decode\b" . --include="*.ts"

# 找没有 whitelist 的 ValidationPipe
grep -rn "ValidationPipe" . --include="*.ts"
# 确认是否有 whitelist: true

# 找 @Body() 没有 DTO 验证的情况
grep -rn "@Body()" . --include="*.ts"
```
