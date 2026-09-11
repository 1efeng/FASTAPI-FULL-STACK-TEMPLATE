# 攻略检索增强设计（Guides Retrieval）

> 状态：**设计定稿，待实现**（2026-09-11）。
> 前置架构见 `docs/architecture.md`（Aegra 版 Resumable Agent Application）；本设计是 travel-planning 技能的第二阶段能力，不改变 Aegra/LangGraph/checkpoint/恢复链路。

## 1. 背景与决策

travel-planning Agent 目前只靠模型知识 + `read_file` 读 SKILL.md 回答，不接触内部攻略语料。团队有 **300~1000 篇分类整齐的旅游攻略**（城市 / 主题 / 人群 / 天数 / 预算 / 季节），希望 agent 基于内部攻略给出带来源的回答，而不是泛泛而谈。

决策（数据驱动，不预设技术）：

1. **开局不用向量检索**。语料分类整齐 + 总量小（1~10MB），"结构化过滤 + 关键词排序"能把候选压到每类 5~15 篇；是否升级到向量由 eval 命中率决定，不因篇数（300 或 1000）触发。
2. **检索是 Agent 工具，不是运行时内置**。沿用"Runtime 复用成熟实现，应用只补治理"：检索能力内聚在 `travel_runtime/guides.py`，通过 `search_guides` / `get_guide` 两个工具暴露给 agent；以后可原样包成 MCP server 给其他运行时复用。
3. **中文检索不依赖 PG 内置分词**。`tsvector` 对中文基本无效；用 `pg_trgm`（子串/模糊匹配）+ 结构化过滤，避免引入 zhparser/jieba 等运维负担。
4. **易变信息不进库**。开放时间、票价、班次等由实时工具核验（沿用 SKILL 既有规则）；库内只存稳定知识与 `verified_at`。

## 2. 目标与非目标

### 目标

- 制定旅行计划且命中内部攻略时，检索并基于全文作答；检索是可用的工具，不是强制步骤
- 回答标注来源标题，检索不到时明确告知并给相邻建议
- 检索过程可 eval、可调优（过滤器 / 排序 / 未来向量融合），工具签名保持稳定

### 非目标（本设计不做）

- 向量检索 / embedding 基建（由 §7 eval 结果决定是否引入）
- 外部数据源（马蜂窝 / 公开搜索）集成——未来可作为 `search_web` 平级工具
- 会话记忆检索、通用知识库平台
- 合作景区 / 交通路线的实体建模（同模式、同一套工具形态，后续单独扩展）

## 3. 数据模型

### 3.1 内容形态

攻略正文用 markdown，元数据用 frontmatter，分类字段使用**受控枚举**（导入时校验，防 300 篇分类漂移）：

```markdown
---
slug: tokyo-7days
title: 东京 7 日经典路线
city: 东京
country: 日本
region: 关东
themes: [经典, 美食]
audiences: [家庭, 情侣]
days_min: 5
days_max: 7
budget_min: 8000
seasons: [春, 秋]
summary: 覆盖经典地标与本地美食的 7 日行程，适合第一次去东京的家庭与情侣。
---
# 东京 7 日经典路线
（正文……）
```

### 3.2 索引表

```sql
CREATE TABLE IF NOT EXISTS travel_guides (
    id          BIGSERIAL PRIMARY KEY,
    slug        VARCHAR(120) UNIQUE NOT NULL,   -- 稳定键，导入幂等依据
    title       VARCHAR(255) NOT NULL,
    city        VARCHAR(80),
    country     VARCHAR(80),
    region      VARCHAR(80),
    themes      TEXT[] NOT NULL DEFAULT '{}',
    audiences   TEXT[] NOT NULL DEFAULT '{}',
    days_min    INT,
    days_max    INT,
    budget_min  INT,
    budget_max  INT,
    seasons     TEXT[] NOT NULL DEFAULT '{}',
    summary     TEXT NOT NULL,
    content     TEXT NOT NULL,
    source_path VARCHAR(255),
    verified_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_guides_city     ON travel_guides (city);
CREATE INDEX IF NOT EXISTS ix_guides_themes   ON travel_guides USING GIN (themes);
CREATE INDEX IF NOT EXISTS ix_guides_audience ON travel_guides USING GIN (audiences);

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS ix_guides_trgm
    ON travel_guides USING GIN (title gin_trgm_ops, summary gin_trgm_ops);
```

- 分类整齐的价值：`city/themes/audiences/days/budget` 是**确定性过滤**，命中率大头靠它们；`title/summary` 的 trgm 只做关键词兜底。
- 后续若加向量：同一张表加 `embedding vector` 列，`search_guides` 内部做混合检索，**工具签名不变**。

## 4. 导入流程

**一条命令处理全部变更（新增 / 更新 / 删除 / 改名）**：

```bash
python agent-runtime/scripts/import_guides.py --dir rag/guides --prune
```

脚本每次运行做两步：

1. **逐个文件 upsert**：解析 frontmatter → 校验必填字段与 `themes/audiences/seasons` 枚举 → `INSERT ... ON CONFLICT (slug) DO UPDATE`（新增插入、已有原地更新）
2. **`--prune` 对齐**：删除"库中存在但目录里已无对应文件"的行（默认开启，`rag/guides/` 是唯一事实源；`--no-prune` 留给部分导入场景）

| 你对文件做了什么 | 脚本行为 | 库里结果 |
| --- | --- | --- |
| 新增 `paris-5days.md` | slug 不在库 → INSERT | 多 1 行 |
| 修改某篇内容 | slug 在库 → 原地 UPDATE | 行数不变，内容更新 |
| 删除某篇文件 | 文件不存在 → DELETE（`--prune`） | 少 1 行 |
| 改名（slug 变化） | 新 slug INSERT + 旧 slug 被 prune | 只剩新 slug 一行 |

每次输出统计：`新增 N / 更新 M / 删除 K / 校验失败 L`。SQL 骨架：

```sql
-- 步骤 1：逐个文件
INSERT INTO travel_guides (slug, title, content, ...)
VALUES (:slug, ...)
ON CONFLICT (slug) DO UPDATE SET
  title = EXCLUDED.title, content = EXCLUDED.content, ...,
  updated_at = now();

-- 步骤 2：--prune 时
DELETE FROM travel_guides
WHERE slug NOT IN (:当前目录所有文件的 slug);
```

部署时机：手动执行或作为一次性容器任务；多实例并发导入用 advisory lock 防锁竞争；不依赖 Alembic（runtime 自管表，同 `tool_invocations` 模式）。

### 4.1 同步模型：全量同步（文件系统即事实源）

每次运行都是**全量同步**：把目录里所有文件逐个 upsert，再 `--prune` 删掉无对应文件的孤儿行。这不是删表重建，而是行级覆盖更新——表始终在，内容与目录对齐到最新状态。

为什么在 ≤1000 篇规模选全量同步而不是增量导入：

- **成本可忽略**：逐行 upsert 秒级完成；增量需要先算每个文件的 content hash、与库比对再决定更新谁，代码复杂度翻倍，换来的时间节省不值。
- **自愈**：库里某行被误删，下次跑自动补回；文件被删除，`--prune` 自动清掉。增量模型没有这个能力。
- **幂等可重跑**：跑多少次结果都一致，天然适合手动/CI/容器任务反复执行。

何时才优化：语料上到数万 / 数十万篇、全量 upsert 过重时，加 `content_hash` 列，只对 hash 变化的行执行 UPDATE，其余跳过；架构与工具契约不变，仍保持 `--prune` 对齐语义。

范本目录已建立：`rag/guides/`（攻略 3 篇）与 `rag/spots/`（景点 3 篇，frontmatter 含 `routes` 结构化路线）。景点为后续扩展实体，P1 只做 `rag/guides/`。

## 5. 检索工具

### 5.1 实现位置

```text
agent-runtime/src/travel_runtime/
├── guides.py        # 表 DDL + GuideStore（复用 db.py 的 get_engine；独立 advisory lock）
├── middleware.py    # + GuidesMiddleware（search_guides / get_guide 两个工具）
└── graph.py         # create_agent middleware 注册 +1
```

### 5.2 工具契约

```python
@tool("search_guides")
def search_guides(
    city: str | None = None,        # 东京
    theme: str | None = None,       # 亲子
    audience: str | None = None,    # 家庭
    days_min: int | None = None,
    days_max: int | None = None,
    keywords: str | None = None,    # 免费、夜景
    limit: int = 5,
) -> str:
    """按结构化条件过滤 + 关键词排序，返回 [{slug, title, city, themes, days, summary}]"""

@tool("get_guide")
def get_guide(slug: str) -> str:
    """按 slug 返回攻略 title + 全文，供 agent 基于内容作答。"""
```

SQL 逻辑：

- 结构化字段精确匹配：`city = :city`、`themes @> ARRAY[:theme]`、`audiences @> ARRAY[:audience]`
- 天数/预算区间过滤
- `keywords` 用 `similarity(title, :kw)` 加权（title 权重高于 summary）
- `ORDER BY` 结构化命中优先 + trgm 相似度，`LIMIT :limit`

### 5.3 治理

- 只读工具，无副作用；`ToolIdempotencyMiddleware` 照常记录，无特殊处理
- `get_guide` 返回内容即"回答依据"，来源 = `title`，可追溯

### 5.4 get_guide 完整实现

先新增 `agent-runtime/src/travel_runtime/guides.py`（表 DDL + `GuideStore`，复用 `db.py` 的 `get_engine`）：

```python
# agent-runtime/src/travel_runtime/guides.py
"""内部攻略索引 store：travel_guides 表，runtime 自管（同 db.py 模式）。"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text

from travel_runtime.db import get_engine  # 复用同一 asyncpg 连接池

# 每条语句单独执行：asyncpg 拒绝一条语句里多个命令
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS travel_guides (
    id          BIGSERIAL PRIMARY KEY,
    slug        VARCHAR(120) UNIQUE NOT NULL,
    title       VARCHAR(255) NOT NULL,
    city        VARCHAR(80),
    country     VARCHAR(80),
    region      VARCHAR(80),
    themes      TEXT[] NOT NULL DEFAULT '{}',
    audiences   TEXT[] NOT NULL DEFAULT '{}',
    days_min    INT,
    days_max    INT,
    budget_min  INT,
    budget_max  INT,
    seasons     TEXT[] NOT NULL DEFAULT '{}',
    summary     TEXT NOT NULL,
    content     TEXT NOT NULL,
    source_path VARCHAR(255),
    verified_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_CREATE_INDEX_CITY = """CREATE INDEX IF NOT EXISTS ix_guides_city ON travel_guides (city)"""
_CREATE_INDEX_THEMES = """CREATE INDEX IF NOT EXISTS ix_guides_themes ON travel_guides USING GIN (themes)"""
_CREATE_INDEX_AUDIENCES = """CREATE INDEX IF NOT EXISTS ix_guides_audiences ON travel_guides USING GIN (audiences)"""
_CREATE_EXT_TRGM = "CREATE EXTENSION IF NOT EXISTS pg_trgm"
_CREATE_INDEX_TRGM = """
CREATE INDEX IF NOT EXISTS ix_guides_trgm
    ON travel_guides USING GIN (title gin_trgm_ops, summary gin_trgm_ops)
"""

_GET_BY_SLUG = text(
    """
    SELECT slug, title, city, themes, days_min, days_max, summary, content
    FROM travel_guides
    WHERE slug = :slug
    LIMIT 1
    """
)

_schema_ready = asyncio.Lock()
_schema_done = False


async def ensure_guides_schema() -> None:
    """幂等建表 + 索引（advisory lock 防多实例并发）。"""
    global _schema_done
    if _schema_done:
        return
    async with _schema_ready:
        if _schema_done:
            return
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('travel_runtime_travel_guides'))")
            )
            await conn.execute(text(_CREATE_TABLE))
            await conn.execute(text(_CREATE_INDEX_CITY))
            await conn.execute(text(_CREATE_INDEX_THEMES))
            await conn.execute(text(_CREATE_INDEX_AUDIENCES))
            await conn.execute(text(_CREATE_EXT_TRGM))
            await conn.execute(text(_CREATE_INDEX_TRGM))
        _schema_done = True


class GuideStore:
    """攻略索引读写（目前只有读取；写入走导入脚本 import_guides.py）。"""

    async def get_by_slug(self, slug: str) -> dict[str, Any] | None:
        await ensure_guides_schema()
        async with get_engine().connect() as conn:
            row = (await conn.execute(_GET_BY_SLUG, {"slug": slug})).first()
        if row is None:
            return None
        return {
            "slug": row[0],
            "title": row[1],
            "city": row[2],
            "themes": row[3],
            "days_min": row[4],
            "days_max": row[5],
            "summary": row[6],
            "content": row[7],
        }
```

再在 `middleware.py` 追加 `GuidesMiddleware`（工具是 async，直接查库返回格式化文本）：

```python
# agent-runtime/src/travel_runtime/middleware.py：追加
from travel_runtime.guides import GuideStore


def _format_guide(guide: dict[str, Any]) -> str:
    themes = "、".join(guide["themes"] or [])
    days = "未标注"
    if guide["days_min"] and guide["days_max"]:
        days = f"{guide['days_min']}-{guide['days_max']} 天"
    return (
        f"# {guide['title']}\n"
        f"城市：{guide['city'] or '未知'} ｜ 主题：{themes or '未知'} ｜ 天数：{days}\n"
        f"摘要：{guide['summary']}\n\n"
        f"{guide['content']}"
    )


class GuidesMiddleware(AgentMiddleware):
    """把内部攻略检索能力暴露给 agent（只读）。"""

    def __init__(self) -> None:
        @tool("get_guide")
        async def get_guide(slug: str) -> str:
            """按 slug 读取一篇内部攻略的完整内容（标题 + 元数据 + 正文）。
            返回内容即回答依据，可引用其中的标题；slug 需先由 search_guides 得到。"""
            guide = await GuideStore().get_by_slug(slug=slug)
            if guide is None:
                return f"未找到攻略 {slug}；请先用 search_guides 确认可用的 slug。"
            return _format_guide(guide)

        # search_guides 按 §5.2 契约加入同一 self.tools（P1 补齐）
        self.tools = [get_guide]
```

`search_guides` 在 P1 与 `get_guide` 一起加入 `self.tools`；它的 SQL（结构化过滤 + trgm 排序）见 §5.2。

## 6. Agent 行为约束

更新 `agent-runtime/src/travel_runtime/skills/travel-planning/SKILL.md`，新增规则（工具使用由模型判断，不做流程化强制）：

> - 仅当问题属于内部攻略能覆盖的范围（行程设计、路线推荐、景点组合、预算/天数建议等）时使用 `search_guides`；普通旅游事实问答、实时信息（开放时间/票价/班次）、通用旅行知识不触发检索。
> - 命中相关攻略时，`get_guide` 读全文后再作答，回答基于攻略内容并标注来源标题。
> - 检索不到或候选不相关时，直接基于模型知识正常回答，不向用户强调"检索失败"；若明显存在相邻攻略（如目标城市没有、邻近城市有），可自然地带一句更合适的建议。
> - 不编造攻略来源：没有命中就不假装引用了攻略。

## 7. Eval 与升级路径

### 7.1 基线 eval

- `eval/retrieval.tsv`：50~100 条 `query<TAB>expected_slug`（覆盖各城市 / 主题 / 人群 / 口语查询）
- `scripts/eval_retrieval.py`：直接调用检索逻辑（不走 agent），输出 top-1 / top-3 命中率与失败样例

### 7.2 升级阶梯（命中率 < 90% 才触发）

1. 过滤器精化：`themes/audiences` 多选、预算/季节区间
2. 排序升级：exact 匹配 > trgm，必要时 BM25 式打分（pg_search / 简单 tf）
3. 向量混合（最后手段）：pgvector `embedding` 列 + 结构化过滤 + RRF 融合，工具签名不变

## 8. 实施顺序

- **P1**：表 + 导入脚本 + 两个工具 + SKILL 接线 + smoke 测试（导入 3~5 篇样例，CLI 直查命中）
- **P2**：eval 集 + 命中率脚本，记录基线
- **P3**：按 eval 结果决定是否进入升级阶梯；同时更新 `AGENTS.md` 的"不引入 RAG"条目为"按本设计数据驱动引入"

## 9. 验收口径

- 攻略类问题（行程/路线/景点组合）→ agent 检索 → 命中时回答含来源标题且内容与攻略一致
- 非攻略类问题 → agent 不触发检索，正常回答
- 检索未命中 → agent 基于自身知识正常回答，不强调检索失败，不编造攻略来源
- eval top-3 命中率有基线记录；未达到 90% 前不引入向量
