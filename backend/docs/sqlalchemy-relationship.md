# SQLAlchemy `relationship()` 核心用法指南

> 面向本项目的日常使用,聚焦常用字段与写法,不展开边界场景。
> 本文以本项目 `User` ↔ `Item` 两个模型([user/model.py](../app/modules/user/model.py)、[item/model.py](../app/modules/item/model.py))为例。

# 一、先拆解 `all, delete-orphan` 底层等价含义
```
cascade="all, delete-orphan"
# all = save-update, merge, refresh-expire, expunge, delete
# delete-orphan 是独立附加规则：子脱离父集合就标记删除
```
适用：**强从属**（用户-私有文件、文章-评论、订单-订单项），子没有独立生命周期。

# 二、生产环境 4 套高频 cascade 组合（按业务场景分）
## 1. 强从属：all, delete-orphan（你当前用的）
### 行为
1. 新增/修改父，自动同步子（save-update）
2. 删除父，Session 内自动删除所有子（delete）
3. 把子从父列表 remove()，子直接被删除（孤儿删除核心特性）
4. 刷新/分离父对象，同步作用到子
### 适用
用户私有Item、笔记附件、帖子评论、购物车商品、租户私有资源
### 配套必加
外键 `ondelete="CASCADE"` + `passive_deletes=True`（大数据量）
```python
items: Mapped[list["Item"]] = relationship(
    back_populates="owner",
    cascade="all, delete-orphan",
    passive_deletes=True,
    lazy="selectin"
)
```

## 2. 弱从属：all（只有删除级联，无孤儿删除）
### 行为
- 删除父 → 同步删所有子
- 把子从父列表 remove()，**不会删除子**，只会清空外键（子可“改嫁”其他父）
### 适用
分类-商品、班级-学生、项目-成员；子实体可转移归属，独立存在
### 示例
```python
products: Mapped[list["Product"]] = relationship(
    back_populates="category",
    cascade="all"
)
```

## 3. 仅同步新增更新，不级联删除（默认无cascade参数就是这套）
不写cascade，默认等价：`cascade="save-update, merge"`
### 行为
1. 新增父时append子，自动保存子
2. 修改子字段，父commit时同步入库
3. **删除父，不会删子**；数据库外键不加CASCADE会抛外键报错
### 适用
多对多角色、订单-公共商品、用户-全局标签；子完全独立，不能随父销毁
### 典型场景
订单关联商品，删除订单不能删商品
```python
goods: Mapped[list["Goods"]] = relationship(back_populates="orders")
```

## 4. 只读关系：cascade="" 空级联 + viewonly=True
### 行为
完全关闭所有级联逻辑，ORM不维护新增、更新、删除，仅用于查询展示
### 适用
统计视图、历史关联只读查询、反向冗余查询字段
```python
# 仅用来查，不做任何增删改
history_records: Mapped[list["Record"]] = relationship(
    back_populates="target",
    viewonly=True,
    cascade=""
)
```

# 三、补充独立常用 cascade 片段（可自由拼接）
1. `delete`：仅开启「删父同步删子」，无孤儿删除
2. `delete-orphan`：必须搭配 delete/all 才能生效，单独写无效
3. `save-update`：append子到父集合，commit自动入库（几乎所有业务必带）
4. `merge`：session.merge() 更新父时同步更新子
5. `expunge`：父对象移出session，子同步移出

# 四、场景快速对照表
| cascade 组合 | 删父删子 | 移除集合删子 | 子能否独立存在 | 业务场景 |
|-------------|----------|--------------|----------------|----------|
| all, delete-orphan | ✅ | ✅ | ❌ 孤儿直接删除 | 用户私有资源、评论、附件 |
| all | ✅ | ❌ 仅清空外键 | ✅ 可改嫁 | 分类商品、班级学生 |
| 不写（save-update,merge） | ❌ | ❌ | ✅ 完全独立 | 订单-商品、多对多角色 |
| cascade="" + viewonly | ❌ | ❌ | ——只读 | 统计、历史查询视图 |

# 五、开发选型口诀
1. 子是父的附属，不能单独存在 → `all, delete-orphan`
2. 子归属于父，但可转移给别的父 → `all`
3. 子是全局公共数据，不能随父删除 → 不填cascade（默认）
4. 只用来查询，不做任何写入操作 → `cascade="" viewonly=True`

---

## 0. 先理解一件事

`relationship()` **不建表、不产生数据库列**。它只是外键的 ORM 投影:

- 数据库里真实存在的是 `item.owner_id` 外键;
- `User.items` / `Item.owner` 是 ORM 根据这条外键"推导"出来的对象视图,访问时会发 SQL 查询。

关系必须成对出现(`User.items` 和 `Item.owner`),通过 `back_populates` 互相绑定,才能两端自动同步。

---

## 1. 三类核心关系

### 1.1 一对多 + 多对一(最常见)

```python
# 一端(一个用户拥有多个 item)
class User(BaseModel):
    items: Mapped[list[Item]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

# 多端(每个 item 属于一个用户)
class Item(BaseModel):
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), comment="所属用户ID"
    )
    owner: Mapped[User | None] = relationship(back_populates="items", lazy="selectin")
```

- `list[Item]` → 集合关系;`Item.owner` 默认 `uselist=False`,是单对象。
- 外键放"多"的一侧(`item.owner_id`)。
- 本项目的标准写法(见 [user/model.py:25-31](../app/modules/user/model.py#L25-L31))。

### 1.2 一对一

一对多基础上,在一端加 `uselist=False`:

```python
class UserProfile(BaseModel):
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), unique=True
    )
    user: Mapped[User] = relationship(back_populates="profile")


class User(BaseModel):
    profile: Mapped[UserProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
```

关键:外键列要加 `unique=True`,配合 `uselist=False` 才是严格一对一。

### 1.3 多对多(需要关联表)

```python
# 关联表(纯中间表,不建模型)
user_role = Table(
    "user_role",
    Base.metadata,
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("role.id", ondelete="CASCADE"), primary_key=True),
)


class User(BaseModel):
    roles: Mapped[list[Role]] = relationship(
        secondary=user_role,  # 通过关联表
        back_populates="users",
        lazy="selectin",
    )


class Role(BaseModel):
    users: Mapped[list[User]] = relationship(
        secondary=user_role, back_populates="roles", lazy="selectin"
    )
```

> 如果中间表还要带额外字段(如"关联时间"),就把它建成正式模型,再用两个一对多拼成多对多。

---

## 2. 核心参数速查(掌握这几个就够了)

| 参数 | 作用 | 常用值 |
|---|---|---|
| `argument` | 目标模型类(第一个位置参数) | 类本身,如 `Item` |
| `back_populates` | 绑定另一端的反向关系名,两端自动同步 | 如 `"owner"` |
| `lazy` | 关系**何时/怎么加载** | `select`(默认)/ `selectin` / `joined` |
| `cascade` | 增删操作如何传播到关联对象 | 默认 / `all, delete-orphan` |
| `uselist` | 是否集合;`False` = 单对象(一对一) | 一对一用 |
| `order_by` | 集合加载后的排序 | 如 `"Item.created_at.desc()"` |
| `secondary` | 多对多的关联表 | 表对象 |
| `viewonly` | 只读关系,ORM 不负责写 | `True`(只读场景) |
| `passive_deletes` | 删父时**不加载子对象**,靠数据库外键级联删 | `True`(数据量大时) |

### lazy 选哪个

| 值 | 行为 | 什么时候用 |
|---|---|---|
| `select` | 访问时才发查询,一次一个父对象 | 基本不用——有 N+1 风险 |
| `selectin` | 父对象加载后,按主键 `IN(...)` 批量查一次 | **默认推荐**,避免 N+1 |
| `joined` | 父查询直接 `LEFT JOIN` | 关系层级浅、一次查出的数据量小时 |

### cascade 选哪个

| 值 | 行为 | 什么时候用 |
|---|---|---|
| (不写,默认 `save-update, merge`) | 删父时**不**删子 | 子对象独立于父存在,如"订单和商品" |
| `all, delete-orphan` | 删父删子;子被移出集合也删 | 子对象从属于父,如"用户和它的 item" |
| `all`(或 `delete`) | 删父时删子;移出集合不删 | 子从属于父,但允许"改嫁"给别的父 |

> 本项目用户与 item 是从属关系,用 `all, delete-orphan`,删除用户时级联清掉名下 item。

---

## 3. 完整可抄的模板

### 一对多(从属关系,本项目的标准形态)

```python
class User(BaseModel):
    items: Mapped[list[Item]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

class Item(BaseModel):
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE")
    )
    owner: Mapped[User | None] = relationship(
        back_populates="items", lazy="selectin"
    )
```

要点:
- 两端 `back_populates` 互指;
- 外键在"多"的一侧,带 `ondelete="CASCADE"` 作为数据库级兜底;
- `lazy="selectin"` 避免列表接口的 N+1;
- 数据库列注释、长度限制按项目惯例补上。

### 集合按时间倒序

```python
items: Mapped[list[Item]] = relationship(
    back_populates="owner",
    cascade="all, delete-orphan",
    lazy="selectin",
    order_by="Item.created_at.desc()",
)
```

---

## 4. API 层的搭配原则(避免 N+1)

关系是懒加载的,在接口里要"用得克制":

1. **Pydantic schema 里只声明需要的字段**。`UserPublic` 不写 `items`,序列化时就碰不到这条关系,一条查询都不多发(本项目 [user/schema.py](../app/modules/user/schema.py) 就是这样做)。
2. 列表接口需要嵌套数据时,用查询级加载明确声明,而不是靠模型默认:

   ```python
   stmt = select(User).options(selectinload(User.items))
   ```

3. 循环里访问 `.items` 前,先想清楚是不是会触发 N+1;`lazy="selectin"` 只对"同一批加载出来的父对象"生效。

---

## 5. 新增一张表时的清单

写模型时对照检查:

- [ ] 继承 `BaseModel`(自动获得 `id` 主键 + `created_at`/`updated_at`)
- [ ] 外键列放"多"的一侧,并加 `ForeignKey(..., ondelete="CASCADE")`
- [ ] 关系成对声明,两端 `back_populates` 互指
- [ ] 集合关系用 `lazy="selectin"`,从属关系用 `cascade="all, delete-orphan"`
- [ ] 需要排序用 `order_by`
- [ ] 记得在 `app/alembic/env.py` 里 import 新模型(否则迁移看不到它)
- [ ] 字段加中文 `comment`
