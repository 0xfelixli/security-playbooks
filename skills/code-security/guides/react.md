---
title: React Code Review Guide
tags: react, code-quality, hooks, performance, rsc, react19, tanstack-query
source: https://github.com/awesome-skills/code-review-skill/blob/main/reference/react.md
---

# React 代码审查指南

React 审查重点：Hooks 规则、性能优化的适度性、组件设计、以及现代 React 19/RSC 模式。

---

## 1. 基础 Hooks 规则

```tsx
// ❌ 条件调用 Hooks — 违反 Hooks 规则
function BadComponent({ isLoggedIn }) {
  if (isLoggedIn) {
    const [user, setUser] = useState(null);  // Error!
  }
}

// ✅ Hooks 必须在组件顶层调用
function GoodComponent({ isLoggedIn }) {
  const [user, setUser] = useState(null);
  if (!isLoggedIn) return <LoginPrompt />;
  return <div>{user?.name}</div>;
}
```

---

## 2. useEffect 模式

```tsx
// ❌ 依赖数组缺失
function BadEffect({ userId }) {
  const [user, setUser] = useState(null);
  useEffect(() => {
    fetchUser(userId).then(setUser);
  }, []);  // 缺少 userId！
}

// ✅ 完整的依赖数组 + 清理函数
function GoodEffect({ userId }) {
  const [user, setUser] = useState(null);
  useEffect(() => {
    let cancelled = false;
    fetchUser(userId).then(data => {
      if (!cancelled) setUser(data);
    });
    return () => { cancelled = true; };
  }, [userId]);
}

// ❌ useEffect 用于派生状态（反模式）
function BadDerived({ items }) {
  const [filteredItems, setFilteredItems] = useState([]);
  useEffect(() => {
    setFilteredItems(items.filter(i => i.active));  // 额外渲染
  }, [items]);
}

// ✅ 直接在渲染时计算
function GoodDerived({ items }) {
  const filteredItems = useMemo(() => items.filter(i => i.active), [items]);
  return <List items={filteredItems} />;
}

// ❌ useEffect 用于事件响应
function BadEventEffect() {
  const [query, setQuery] = useState('');
  useEffect(() => {
    if (query) analytics.track('search', { query });  // 应在事件处理器里
  }, [query]);
}

// ✅ 在事件处理器中执行副作用
function GoodEvent() {
  const handleSearch = (q: string) => {
    setQuery(q);
    analytics.track('search', { query: q });
  };
}
```

---

## 3. useMemo / useCallback

```tsx
// ❌ 过度优化 — 常量不需要 useMemo/useCallback
function OverOptimized() {
  const config = useMemo(() => ({ timeout: 5000 }), []);  // 无意义
  const handleClick = useCallback(() => console.log('clicked'), []);  // 无意义
}

// ✅ 只在配合 React.memo 时才有意义
const MemoizedChild = React.memo(function Child({ onClick, items }) {
  return <div onClick={onClick}>{items.length}</div>;
});

function Parent({ rawItems }) {
  const items = useMemo(() => processItems(rawItems), [rawItems]);
  const handleClick = useCallback(() => console.log(items.length), [items]);
  return <MemoizedChild onClick={handleClick} items={items} />;
}
```

---

## 4. 组件设计

```tsx
// ❌ 在组件内定义组件 — 每次渲染都创建新组件
function BadParent() {
  function ChildComponent() { return <div>child</div>; }
  return <ChildComponent />;
}

// ✅ 组件定义在外部
function ChildComponent() { return <div>child</div>; }
function GoodParent() { return <ChildComponent />; }

// ❌ Props 总是新对象引用，memo 失效
function BadProps() {
  return <MemoizedComponent style={{ color: 'red' }} onClick={() => {}} />;
}

// ✅ 稳定的引用
const style = { color: 'red' };
function GoodProps() {
  const handleClick = useCallback(() => {}, []);
  return <MemoizedComponent style={style} onClick={handleClick} />;
}
```

---

## 5. Error Boundaries & Suspense

```tsx
// ❌ 没有错误边界，错误导致整个应用崩溃
function BadApp() {
  return (
    <Suspense fallback={<Loading />}>
      <DataComponent />
    </Suspense>
  );
}

// ✅ Error Boundary 包裹 Suspense
function GoodApp() {
  return (
    <ErrorBoundary fallback={<ErrorUI />}>
      <Suspense fallback={<Loading />}>
        <DataComponent />
      </Suspense>
    </ErrorBoundary>
  );
}

// ✅ 独立 Suspense 边界，各部分独立加载
function GoodLayout() {
  return (
    <>
      <Header />
      <div className="flex">
        <Suspense fallback={<ContentSkeleton />}>
          <MainContent />
        </Suspense>
        <Suspense fallback={<SidebarSkeleton />}>
          <Sidebar />
        </Suspense>
      </div>
    </>
  );
}
```

---

## 6. Server Components (RSC)

```tsx
// ❌ 在 Server Component 中使用客户端特性
function BadServerComponent() {
  const [count, setCount] = useState(0);  // Error! RSC 不能用 Hooks
}

// ✅ 交互逻辑提取到 Client Component
'use client';
function Counter() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(c => c + 1)}>{count}</button>;
}

// Server Component 直接 await
async function GoodServerComponent() {
  const data = await fetchData();
  return (
    <div>
      <h1>{data.title}</h1>
      <Counter />
    </div>
  );
}

// ❌ 'use client' 放在 layout 顶层 — 整个树都变成客户端
// ✅ 只在需要交互的叶子组件使用 'use client'
```

---

## 7. React 19 Actions & Forms

### useActionState

```tsx
// ❌ 传统方式：多个状态变量
function OldForm() {
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState(null);
  // ...
}

// ✅ React 19: useActionState 统一管理
function NewForm() {
  const [state, formAction, isPending] = useActionState(
    async (prevState, formData: FormData) => {
      try {
        const result = await submitForm(formData);
        return { success: true, data: result };
      } catch (e) {
        return { success: false, error: e.message };
      }
    },
    { success: false, data: null, error: null }
  );

  return (
    <form action={formAction}>
      <input name="email" />
      <button disabled={isPending}>{isPending ? 'Submitting...' : 'Submit'}</button>
      {state.error && <p>{state.error}</p>}
    </form>
  );
}
```

### useFormStatus

```tsx
// ✅ useFormStatus 访问父 <form> 状态，必须在 form 的子组件中调用
function SubmitButton() {
  const { pending } = useFormStatus();
  return <button disabled={pending}>{pending ? 'Submitting...' : 'Submit'}</button>;
}

// ❌ useFormStatus 在 form 同级调用 — 获取不到状态
function BadForm() {
  const { pending } = useFormStatus();  // 无效！
  return <form action={action}><button disabled={pending}>Submit</button></form>;
}
```

### useOptimistic

```tsx
// ✅ 即时反馈，失败自动回滚
function FastLike({ postId, likes }) {
  const [optimisticLikes, addOptimisticLike] = useOptimistic(
    likes,
    (current, increment: number) => current + increment
  );

  const handleLike = async () => {
    addOptimisticLike(1);
    try {
      await likePost(postId);
    } catch {
      // React 自动回滚
    }
  };

  return <button onClick={handleLike}>{optimisticLikes} likes</button>;
}
```

---

## 8. TanStack Query v5

```tsx
// ✅ 推荐生产配置
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,   // 5 分钟
      gcTime: 1000 * 60 * 30,     // 30 分钟
      retry: 3,
    },
  },
});

// ✅ queryOptions 统一定义，避免重复
const userQueryOptions = (userId: string) =>
  queryOptions({
    queryKey: ['users', userId],
    queryFn: () => fetchUser(userId),
  });

// ❌ queryKey 没有包含所有影响数据的参数
useQuery({ queryKey: ['items'], queryFn: () => fetchItems(filters) });

// ✅ queryKey 包含所有参数
useQuery({ queryKey: ['items', filters], queryFn: () => fetchItems(filters) });

// ❌ staleTime 默认 0 — 每次挂载都重新请求
// ✅ 设置合理的 staleTime
useQuery({ queryKey: ['data'], queryFn: fetchData, staleTime: 60_000 });
```

### useSuspenseQuery 限制

| 特性 | useQuery | useSuspenseQuery |
|------|----------|------------------|
| `enabled` 选项 | ✅ 支持 | ❌ 不支持 |
| `data` 类型 | `T \| undefined` | `T`（保证有值）|
| 错误处理 | `error` 属性 | 抛出到 Error Boundary |

```tsx
// ❌ useSuspenseQuery 不支持 enabled
useQuery({ ..., enabled: !!userId });  // 改用条件渲染

// ✅ 父组件控制条件渲染
function Parent({ userId }) {
  if (!userId) return <NoUserSelected />;
  return (
    <Suspense fallback={<Skeleton />}>
      <UserComponent userId={userId} />
    </Suspense>
  );
}
```

---

## Review Checklists

### Hooks 规则
- [ ] Hooks 在组件/自定义 Hook 顶层调用，无条件/循环调用
- [ ] useEffect 依赖数组完整
- [ ] useEffect 有清理函数（订阅/定时器/请求）
- [ ] 没有用 useEffect 计算派生状态

### 性能优化（适度原则）
- [ ] useMemo/useCallback 只用于真正需要的场景（配合 React.memo）
- [ ] 没有在组件内定义子组件
- [ ] 长列表使用虚拟化

### 组件设计
- [ ] 组件职责单一，不超过 200 行
- [ ] Props 接口清晰，使用 TypeScript

### 状态管理
- [ ] 状态就近原则（最小必要范围）
- [ ] 派生状态直接计算，不用 useState 存储

### Server Components (RSC)
- [ ] 'use client' 只用于需要交互的组件
- [ ] 客户端组件尽量放在叶子节点

### React 19 Forms
- [ ] useFormStatus 在 form 子组件中调用
- [ ] useOptimistic 不用于关键业务（支付等）

### TanStack Query
- [ ] queryKey 包含所有影响数据的参数
- [ ] 设置合理的 staleTime（非默认 0）
- [ ] useSuspenseQuery 不使用 enabled
