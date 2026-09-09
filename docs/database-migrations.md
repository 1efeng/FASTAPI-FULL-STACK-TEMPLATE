# 数据库迁移指南

本项目使用 Alembic 管理 PostgreSQL 表结构。所有表变更必须通过迁移文件，禁止手动修改数据库或使用 `create_all`。

## 前置条件

- 确保数据库已启动：`docker compose up -d db`
- 后端依赖已安装：`cd backend && uv sync`
- 本地开发时 `.env` 中 `POSTGRES_HOST_PORT=5433`（因为 5432 被其他项目占用），后端连接时需设置 `POSTGRES_PORT=5433`

以下命令均在 `backend/` 目录下执行。

## 生成迁移文件

修改了 SQLAlchemy 模型后，运行：

```bash
POSTGRES_PORT=5433 uv run alembic revision --autogenerate -m "描述你的变更"
```

Alembic 会对比当前模型和数据库的实际表结构，自动生成增量迁移脚本，文件出现在 `alembic/versions/` 下。

**生成后必须检查生成的文件**，确认：

1. `upgrade()` 里的操作和你的预期一致
2. `downgrade()` 能正确回滚
3. 没有意外的表或列被删除（比如模型里漏写了某个字段，autogenerate 会把它当成"删除"）

如果需要调整，直接编辑迁移文件。

## 提交到数据库

```bash
POSTGRES_PORT=5433 uv run alembic upgrade head
```

这会将所有未应用的迁移按顺序执行到最新版本。

常用命令：

| 命令 | 说明 |
|------|------|
| `alembic upgrade head` | 执行到最新版本 |
| `alembic downgrade -1` | 回滚上一次迁移 |
| `alembic current` | 查看数据库当前在哪个版本 |
| `alembic history` | 查看迁移历史 |
| `alembic heads` | 查看最新的迁移版本号 |

## 初始化数据

迁移完成后运行初始化脚本创建超级用户：

```bash
POSTGRES_PORT=5433 uv run python scripts/init_data.py
```

## 一键启动（推荐）

`bun run dev:all` 会自动完成：启动数据库 → 等待就绪 → `prestart.py`（检查连接）→ `alembic upgrade head` → `init_data.py` → 启动前后端。

改完模型后重启 dev:all 即可，不需要手动跑迁移。

## 团队协作流程

### 场景一：你改了模型，需要生成迁移

1. 修改 `app/` 下的 SQLAlchemy 模型
2. `alembic revision --autogenerate -m "..."` 生成迁移
3. 检查生成的文件内容
4. `alembic upgrade head` 应用到本地数据库
5. 将模型变更和迁移文件一起提交（同一个 commit / PR）

### 场景二：你拉了别人的代码，数据库需要更新

1. `git pull` 拉到最新代码（包含新的迁移文件）
2. `alembic upgrade head` 应用到本地数据库
3. `python scripts/init_data.py`（如果是首次或需要重建初始数据）

### 场景三：迁移文件冲突（两个人同时生成了迁移）

如果两个分支各自生成了迁移，合并时会出现分支冲突（alembic 的 `down_revision` 指向同一个父版本）。

解决方式：

```bash
# 合并后查看 heads，会显示两个 head
alembic heads

# 创建一个 merge migration
alembic merge -m "merge branches" <head1> <head2>

# 然后正常 upgrade
alembic upgrade head
```

### 场景四：需要回滚

```bash
# 回滚上一次迁移
alembic downgrade -1

# 回滚到指定版本
alembic downgrade <revision_id>

# 回滚全部（慎用）
alembic downgrade base
```

注意：`downgrade` 会执行迁移文件中的 `downgrade()` 函数。如果回滚涉及删表/删列，数据会丢失。

## 规则

1. **每次修改模型必须生成迁移文件**，不允许跳过
2. **迁移文件一旦合入 main，不要修改或删除**，只能追加新的迁移
3. **模型和迁移文件在同一个 commit/PR 中提交**，避免别人拉代码后 upgrade 出错
4. **不要手动操作数据库**（psql 改表、drop table 等），所有变更走迁移
5. **不要在迁移文件里写业务逻辑**，迁移只负责表结构变更
