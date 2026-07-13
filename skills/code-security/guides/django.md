---
title: Django / DRF Code Quality Guide
tags: django, drf, python, n+1, serializer, viewset, async, orm
source: https://github.com/awesome-skills/code-review-skill/blob/main/reference/django.md
note: 安全相关内容见 rules/framework-django.md
---

# Django / DRF 代码质量指南

N+1 优化、Serializer 反模式、ViewSet 最佳实践、Async 视图。安全规则见 `rules/framework-django.md`。

---

## 1. N+1 查询优化

### select_related（ForeignKey / OneToOne）

```python
# ❌ N+1：每本书查一次出版社
books = Book.objects.all()
for book in books:
    print(book.publisher.name)  # 额外 N 条查询

# ✅ 一次 JOIN 查询
books = Book.objects.select_related("publisher")
for book in books:
    print(book.publisher.name)  # 无额外查询

# ✅ 多层关系
books = Book.objects.select_related("publisher", "publisher__country")
```

### prefetch_related（M2M / 反向 ForeignKey）

```python
# ❌ N+1：每个作者查一次书
authors = Author.objects.all()
for author in authors:
    print(author.books.all())

# ✅ 两条查询 + Python 合并
authors = Author.objects.prefetch_related("books")

# ✅ 使用 Prefetch 对象控制预查行为
from django.db.models import Prefetch

authors = Author.objects.prefetch_related(
    Prefetch(
        "books",
        queryset=Book.objects.filter(published=True).only("title", "author_id"),
        to_attr="published_books",
    )
)
```

### QuerySet 缓存与计数

```python
# ❌ len() 加载全部对象到内存
total = len(Book.objects.all())

# ✅ count() 在数据库端计数
total = Book.objects.count()

# ❌ if qs 加载全部记录
if Book.objects.filter(author_id=author_id):
    ...

# ✅ exists() 只检查是否有记录
if Book.objects.filter(author_id=author_id).exists():
    ...
```

---

## 2. Serializer 反模式

### 避免 `fields = "__all__"`

```python
# ❌ 暴露所有字段，包括密码 hash、is_superuser
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = "__all__"

# ✅ 显式字段列表
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]

# ✅ 密码 write_only
class RegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password"]

    def create(self, validated_data):
        user = User(**validated_data)
        user.set_password(validated_data["password"])
        user.save()
        return user
```

### 字段级和对象级验证

```python
class OrderSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(min_value=1, max_value=100)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)

    class Meta:
        model = Order
        fields = ["quantity", "price", "discount"]

    def validate(self, attrs):
        if attrs.get("discount", 0) > 0.5 and attrs.get("quantity", 0) < 10:
            raise serializers.ValidationError("Bulk discount requires minimum 10 items.")
        return attrs
```

### 嵌套写入

```python
# ❌ 嵌套 Serializer 没有实现 create/update，写入会失败
class ArticleSerializer(serializers.ModelSerializer):
    tags = TagSerializer(many=True)  # 嵌套写入失败

# ✅ 方案1：嵌套只读 + PrimaryKeyRelatedField 写入
class ArticleSerializer(serializers.ModelSerializer):
    tags = TagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(), many=True, write_only=True, source="tags"
    )

# ✅ 方案2：实现 create()/update()
class ArticleSerializer(serializers.ModelSerializer):
    tags = TagSerializer(many=True)

    def create(self, validated_data):
        tags_data = validated_data.pop("tags")
        article = Article.objects.create(**validated_data)
        for tag_data in tags_data:
            tag, _ = Tag.objects.get_or_create(**tag_data)
            article.tags.add(tag)
        return article
```

### read_only_fields 不能遗漏

```python
# ❌ created_at、author 可被客户端篡改
class CommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = ["id", "body", "author", "created_at"]

# ✅ 标记只读字段
class CommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = ["id", "body", "author", "created_at"]
        read_only_fields = ["author", "created_at"]
```

---

## 3. ViewSet 最佳实践

### 选择正确的基类

```python
# ❌ ModelViewSet 暴露完整 CRUD，但只需要读取
class TagViewSet(viewsets.ModelViewSet):
    queryset = Tag.objects.all()

# ✅ 只读场景
class TagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
```

### 用 `get_queryset()` 限定用户数据范围

```python
# ❌ 任何用户可以看到所有数据
class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()

# ✅ 限定当前用户
class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer

    def get_queryset(self):
        return Document.objects.filter(owner=self.request.user).select_related("owner")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
```

### 权限控制

```python
# ❌ 没有权限控制
class ArticleViewSet(viewsets.ModelViewSet):
    queryset = Article.objects.all()

# ✅ 类级别权限
class ArticleViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

# ✅ 操作级别权限
def get_permissions(self):
    if self.action in ("list", "retrieve"):
        return [permissions.AllowAny()]
    if self.action == "create":
        return [permissions.IsAuthenticated()]
    return [permissions.IsAdminUser()]
```

### 分页和节流

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
    },
}
```

---

## 4. 异步视图

### 在 async 视图中正确使用 ORM

```python
# ❌ 在 async 视图中调用同步 ORM — 阻塞事件循环
async def user_list(request):
    users = User.objects.all()  # 同步调用！
    data = [{"id": u.id} for u in users]
    return JsonResponse(data, safe=False)

# ✅ Django 4.1+ async ORM
async def user_list(request):
    data = []
    async for user in User.objects.all():
        data.append({"id": user.id, "name": user.username})
    return JsonResponse(data, safe=False)

# ✅ aget / afilter
async def user_detail(request, pk):
    user = await User.objects.aget(pk=pk)
    return JsonResponse({"id": user.id})

# ✅ 复杂查询用 sync_to_async
@sync_to_async
def get_user_with_profile(pk):
    return User.objects.select_related("profile").get(pk=pk)
```

### 不要忘记 await

```python
# ❌ 忘记 await — 返回协程对象而非数据
async def user_detail(request, pk):
    user = User.objects.aget(pk=pk)  # 缺少 await！
    return JsonResponse({"name": user.username})  # RuntimeError

# ✅ 始终 await
async def user_detail(request, pk):
    user = await User.objects.aget(pk=pk)
    return JsonResponse({"name": user.username})
```

### 异步视图中的事务

```python
# ❌ transaction.atomic() 是同步的，不能在 async 中直接用
async def create_order(request):
    async with transaction.atomic():  # Error!
        ...

# ✅ 用 sync_to_async 包装事务块
@sync_to_async
def _create_order_with_items():
    with transaction.atomic():
        order = Order.objects.create(total=100)
        OrderItem.objects.create(order=order, product_id=1)
        return order.id

async def create_order(request):
    order_id = await _create_order_with_items()
    return JsonResponse({"order_id": order_id})
```

### 同步中间件拖慢 async 性能

```python
# ❌ 同步中间件会把 async 视图降级为同步执行
class TimingMiddleware:
    def __call__(self, request):  # sync — 阻塞 async 视图
        ...

# ✅ 同时支持 sync 和 async 的中间件
class TimingMiddleware:
    async_capable = True
    sync_capable = True

    async def __acall__(self, request):
        start = time.time()
        response = await self.get_response(request)
        response["X-Elapsed"] = str(time.time() - start)
        return response

    def __call__(self, request):
        start = time.time()
        response = self.get_response(request)
        response["X-Elapsed"] = str(time.time() - start)
        return response
```

---

## Review Checklist

### N+1 查询
- [ ] ForeignKey/OneToOne 关系使用 `select_related()`
- [ ] M2M/反向外键使用 `prefetch_related()`
- [ ] 计数用 `count()`，不用 `len(qs)`
- [ ] 存在性检查用 `exists()`，不用 `if qs`

### Serializer
- [ ] 没有 `fields = "__all__"` 在敏感模型上
- [ ] 密码等敏感字段标记 `write_only=True`
- [ ] 有字段级和对象级验证
- [ ] `read_only_fields` 覆盖 created_at、owner 等自动字段
- [ ] 嵌套写入实现了 `create()`/`update()`

### ViewSet
- [ ] 有显式的 `permission_classes`
- [ ] `get_queryset()` 按当前用户过滤
- [ ] `perform_create()` 关联当前用户
- [ ] 全局或 ViewSet 级分页和节流配置

### 异步视图
- [ ] async 视图内无同步 ORM 调用（使用 `aget`、`afilter`、`async for`）
- [ ] 所有异步 ORM 调用都有 `await`
- [ ] 事务操作用 `sync_to_async` 包装
- [ ] 中间件标记 `async_capable = True`
