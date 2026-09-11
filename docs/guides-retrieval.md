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

- 制定旅行计划前，agent 先检索内部攻略，命中后读全文再作答
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

`agent-runtime/scripts/import_guides.py`：

- 读取 `guides/`（或 `--dir` 指向现有攻略仓库）下 markdown，解析 frontmatter
- 校验必填字段 + `themes/audiences/seasons` 枚举合法性，不合法报错并统计
- `INSERT ... ON CONFLICT (slug) DO UPDATE` 幂等 upsert，可重跑
- 输出统计：总数 / 新增 / 更新 / 校验失败

部署时机：手动执行或作为一次性容器任务；不依赖 Alembic（runtime 自管表，同 `tool_invocations` 模式）。

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

## 6. Agent 行为约束

更新 `agent-runtime/src/travel_runtime/skills/travel-planning/SKILL.md`，新增硬规则：

> 制定计划前必须先 `search_guides` 检索内部攻略；命中后 `get_guide` 读全文再作答；回答必须基于攻略内容并标注来源标题；检索不到时明确告知，并给出相邻分类建议（如城市换主题）。不编造攻略来源。

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

- 用户提问 → agent 先检索 → 回答包含攻略来源标题 → 内容与攻略正文一致
- 检索不到 → agent 明确告知可用范围，不编造
- eval top-3 命中率有基线记录；未达到 90% 前不引入向量
