可以，沣。现在把我们这一轮关于 `search_agent / research_agent` 的设计收敛成一版完整架构。

# Search / Research Agent 架构总览

先统一命名：

> 它本质上不是“搜索 Agent”，而是 **Research Agent / Context Compressor**。

它的价值不是“替 Main 搜东西”，而是：

> **把高上下文成本、需要独立研究的子问题放到隔离上下文中处理，最后只把压缩后的 Findings 返回 Main。**

整体结构：

```text
User
  ↓
Main Agent
  ↓
Candidate Plan
  ↓
Reality Gaps
  ↓
Routing Decision
  ├─ Deterministic Fact Work
  │      ↓
  │   Main Direct Tools
  │
  └─ Open-ended Research Topic
         ↓
     research_agent
         ↓
     Planner
         ↓
     Bounded Evidence Batch
         ↓
     Host-owned Tools
         ↓
     Finalizer / Compressor
         ↓
     Host Attestation
         ↓
     ResearchFindings
         ↓
     Main revises plan
         ↓
     Final Answer
```

---

# 一、Main 和 Research Agent 的职责边界

## Main Agent

Main 永远拥有：

```text
用户意图
Candidate Plan
Reality Gap 识别
是否委托 Research
Research Topic 定义
最终路线取舍
最终预算
最终计划
最终回答
```

Main 是 **orchestrator / manager**。

这对应成熟框架里的：

```text
Manager
→ Agent as Tool
→ Manager synthesizes
```

而不是 handoff。

Research Agent 不接管用户对话。

---

## Research Agent

Research Agent 只负责：

```text
一个 bounded research topic
↓
收集必要 evidence
↓
处理 evidence
↓
压缩成 Findings
```

它不能：

```text
生成完整 itinerary
决定住宿
决定整个路线
决定最终预算
替 Main 回答用户
调用其他 Agent
自由无限研究
```

一句话：

> **Main owns decisions；Research owns isolated evidence work。**

---

# 二、什么时候调用 Research Agent

这是最重要的 Routing Gate。

默认：

```text
Main Direct
```

只有满足 Research 条件时才 delegate。

## 不应该调用 Research Agent

如果任务执行路径在开始前已经知道：

```text
查开放时间
查预约
查票价
查天气
查路线
查附近 POI
```

即使有：

```text
3 个 Search
4 个 POI
2 个 Maps
```

也不构成 Research Agent 理由。

因为：

> **Tool 数量 ≠ Agentic Complexity。**

例如：

```text
故宫开放
天坛门票
颐和园预约
八达岭票价
```

应该：

```text
Main
→ parallel tools
```

而不是 delegate。

---

# 三、三层 Routing 模型

Routing 不是两元决策（Main vs Research），而是三层。真正的 path-dependence 属于 Main 的分阶段 orchestration，不属于单次 child。

## A. Main Direct

适合：

```text
单个当前事实
多个 predetermined facts
查询 / Tool 集合事先明确
evidence 较轻
不值得独立 context
```

即使需要：

```text
3 个 Search
2 个 Maps
多个 POI
```

只要 queries / tools 可以在开始前确定，且 evidence 不重，仍应 Main parallel tools。

> **Tool 数量 ≠ Agentic Complexity。**

## B. 单次 research_agent

适合一个 coherent bounded Research Topic，它必须同时满足：

```text
bounded
coherent
upfront-batchable
evidence-heavy
context-isolation valuable
compressible
```

展开：

### 1. Bounded + Coherent

一个 Topic 是一个统一的决策问题，可以提前拆成 atomic verification_items。

### 2. Upfront-batchable

Planner 能一次规划有限的 evidence batch，而不是走一步看一步。

### 3. Evidence-heavy

中间会产生很多：

```text
search results
web pages
comparison evidence
tool results
```

这些东西如果全部进入 Main history，会污染后续规划上下文。

### 4. Compressible

最后可以压缩成：

```text
结论
关键依据
verified / conflicting / unresolved
```

如果 Research 最终还得把 20K evidence 全交给 Main，那 subagent 没价值。

## C. Path-dependent research process

真正的 Search → Observe → Search-again 动态探索，**不属于单次 research_agent**，而是 Main 的分阶段 orchestration：

```text
Research A
→ Main 根据 Findings
→ 发现新的 Reality Gap
→ Research B
```

单次 bounded research_agent 不承担自由 path-dependent 探索；它一次规划一个 evidence batch，证据不足就 unresolved 返回，由 Main 决定是否产生新的 Topic。

---

# 四、典型例子

## 不应该 Research

```text
“八达岭8月28日开不开？”
```

Main Search。

```text
“八达岭开放、预约、高铁、返程耗时分别是多少？”
```

如果查询集合已经明确：

```text
parallel:
  search opening
  search reservation
  search railway
  maps
```

仍然 Main。

甚至：

> “八达岭游玩后赶18:30北京西站高铁是否可行？”

如果研究图已经能预先确定：

```text
开放
铁路
路线
buffer calculation
```

也不一定值得 Research。

---

## 适合 Research

例如：

> “结合东京、箱根、京都、大阪、广岛10日路线，比较全国 JR Pass、区域 Pass 与单买组合，判断哪种更适合当前路线。”

这是一个 bounded evidence-heavy 对比研究：Main 已经定义 Research boundary（价格、覆盖范围、关键组合），child 负责一次性规划 evidence batch 并压缩返回。

```text
verification_items:
  jr-pass-price
  route-coverage
  regional-pass-scope
  key-segment-cost
```

最终压成：

```text
推荐组合 A
预计成本
为什么优于 B/C
适用条件
未确认项
```

注意：如果后续发现新的区域 Pass 候选需要进一步研究，由 Main 生成新的 Research Topic，而不是 child 自己无限 Search-again。

---

# 五、Main → Research Agent 应传什么

核心原则：

> **传 WHAT / WHY / DONE CONDITION，不传 HOW。**

正式 Handoff Contract：

```python
ResearchRequest
├── title
├── objective
├── verification_items
├── context
└── constraints
```

---

## `objective`

定义：

> Research 最终要替 Main 弄清楚什么。

应该是 decision-oriented：

```text
比较当前路线下 JR Pass、区域 Pass 与单买组合，
判断哪种方案最合适。
```

而不是：

```text
调查日本交通
```

---

## `verification_items`

这是：

> **这个 Topic 必须从外部世界确认哪些原子事实。**

例如：

```json
[
  {
    "id": "jr-pass-price",
    "entity": "JR Pass",
    "aspect": "当前价格",
    "question": "当前成人普通席7日券价格是多少？"
  },
  {
    "id": "coverage",
    "entity": "当前路线",
    "aspect": "覆盖范围",
    "question": "哪些关键城际段可由 JR Pass 覆盖？"
  }
]
```

注意：

```text
verification_items
≠ search queries
≠ reasoning steps
≠ tool sequence
```

它表达的是：

> **什么事实需要被证明。**

---

# 六、`verification_items` 应该成为强 contract

当前实现还有一个需要修正的点：

```python
verification_items = []
```

现在是合法的。

这不应该成为生产正常路径。

建议：

```python
verification_items: list[VerificationItem] = Field(
    min_length=1
)
```

因为如果 Main 连：

> “Research 成功到底需要确认什么？”

都说不清楚，就不应该 delegate。

---

# 七、`context`

只传：

> 完成这个 Research Topic 所需的最小 Candidate Plan 片段。

例如：

```text
Day 4 东京→箱根
Day 5 箱根→京都
两名成人
```

不要传：

```text
完整 conversation
完整10日 itinerary
全部 Main tool history
Main reasoning
系统 prompt
```

Research Agent 应该拥有 clean context。

---

# 八、`constraints`

只包含会改变研究判断的硬条件：

```text
日期
人数
儿童年龄
公共交通
预算
不能换酒店
固定返程时间
```

例如：

```json
[
  "2名成人",
  "2026-10-03 至 2026-10-12",
  "优先铁路",
  "不接受夜间巴士"
]
```

---

# 九、绝对不要传什么

Main 不应该传：

```text
search query 列表
工具顺序
worker 数量
research axes
完整历史
全部搜索结果
Main reasoning
```

尤其是：

```json
{
  "queries": [
    "...",
    "...",
    "..."
  ]
}
```

如果 Main 已经能写出完整 query 集合：

> **那这个任务很可能本来就应该 Main Direct。**

---

# 十、Research Agent 内部执行架构

生产 Research Agent 应该保持 bounded。

目标架构：

```text
ResearchRequest
      ↓
Planner
      ↓
ResearchPlan
      ↓
Host parallel tools
      ↓
optional authoritative fetch
      ↓
Evidence Packets
      ↓
Finalizer
      ↓
ResearchFindingsDraft
      ↓
Host normalization
      ↓
Host evidence attestation
      ↓
ResearchFindings
```

不是：

```text
Search
↓
LLM
↓
Search
↓
LLM
↓
Fetch
↓
LLM
↓
Search again
↓
...
```

旧 free-running loop 已经通过 benchmark 证明会导致：

```text
context explosion
tool duplication
non-convergence
token explosion
```

---

# 十一、Planner 的职责

Planner 只负责：

> **把 verification items 转成最小 evidence batch。**

例如：

```text
verification item:
故宫开放规则

→ search_web(authoritative)
```

或者：

```text
return transport

→ search_maps
+ 必要 railway search
```

Planner 不回答问题。

也不能自由扩展 scope。

---

# 十二、Planner Action 必须绑定 Verification Item

当前还需要修：

```python
item_ids: list[str] = Field(
    default_factory=list
)
```

真实 benchmark 已经出现：

```text
item_ids=[]
```

应该改成：

```python
item_ids: list[str] = Field(
    min_length=1,
    max_length=2
)
```

同时 Host 校验：

```text
action.item_ids
⊆
request.verification_item_ids
```

否则 Planner 可以绕过 Topic contract。

---

# 十三、Host 执行 Tools

工具执行属于 Host ownership：

```text
search_web
web_fetch
search_maps
weather
POI
```

Research model 不直接拥有网络现实。

Host 负责：

```text
真实执行
错误处理
source trace
evidence trace
attestation
```

这是很重要的 trust boundary：

```text
Model proposes
Host executes
Host observes
Host attests
```

---

# 十四、Research 内不能无限 Search-again

核心原则：

```text
one bounded evidence batch
```

证据：

```text
足够
→ verified

冲突
→ conflicting

不足
→ unresolved
```

然后立即返回 Main。

不要：

```text
证据不够
→ 再搜
→ 再搜
→ 再搜
```

---

# 十五、ResearchFindings

返回 Main 的应该只是压缩结果：

```python
ResearchFindings
├── topic
├── summary
├── verification_results
├── claims
├── sources
└── unresolved
```

例如：

```json
{
  "topic": "JR Pass 方案比较",
  "summary": "当前路线下全国 JR Pass 不划算，区域 Pass + 单买更合适。",
  "verification_results": [...],
  "claims": [...],
  "sources": [...],
  "unresolved": [...]
}
```

Main 不应该看到：

```text
20条 search results
fetch body
research trajectory
child reasoning
Planner prompt
```

这才叫 Context Isolation。

---

# 十六、状态语义

当前：

```text
verified
conflicting
unresolved
```

这是合理的 evidence semantics。

但需要区分：

### 行业共识

Main 应充分利用 specialist result，不做无意义重复研究。

### 我们自己的项目 policy

像：

```text
verified = CLOSED
```

这不是行业标准协议。

如果只是写在 Skill：

```text
Main 禁止再搜
```

但 runtime 完全允许，那只是 soft prompt。

因此当前更合理的是：

```text
Findings 已充分回答同一 scope 时，
Main 不应重复调查。

conflicting / unresolved / new evidence
才允许继续。
```

不要先引入一个假的强状态机。

如果以后真要“绝对禁止”，再实现：

```text
Runtime Research Ledger
```

---

# 十七、失败语义

Research Agent 失败：

```text
≠ Main 失败
```

正确行为：

```text
search failure
fetch failure
provider failure
evidence insufficient
      ↓
unresolved
      ↓
return Main
```

Main 决定：

```text
采用保守方案
修改 itinerary
忽略非关键项
直接说明不确定性
```

只有真正系统级 failure / cancellation 才应该终止整个 Product request。

---

# 十八、Research Agent 和 Main Tool 的关系

完整 routing（三层模型）：

```text
Reality Gap
    ↓
Queries / Tools 是否能在开始前预先确定？
    │
    ├─ YES（predetermined / lightweight fact work）
    │    ↓
    │   Main Direct
    │   parallel tools if possible
    │
    └─ NO（真正需要探索）
         ↓
    是否存在需要隔离的 evidence-heavy
    bounded Research Topic？
         │
         ├─ NO
         │    → Main / deterministic workflow
         │
         └─ YES
              ↓
    Topic 是否能由 Main 提前拆成
    atomic verification_items、
    Planner 一次规划 evidence batch、
    最终高度压缩？
              │
              ├─ NO → Main（不 delegate）
              │
              └─ YES
                   ↓
              research_agent（单次 bounded batch）
```

如果单个 Topic 无法一次 bounded 解决，而是依赖前一步发现才能定义下一步，那么 path-dependence 属于 Main 的分阶段 orchestration：

```text
Research A → Main → 新的 Reality Gap → Research B
```

而不是在 child 内自由 Search-again。

---

# 十九、多个 Research Topics

允许：

```text
0..N
```

不定死数量。

如果 Topics 独立：

```text
Research A ─┐
Research B ─┼→ Main
Research C ─┘
```

可以并行。

如果有依赖：

```text
Research A
↓
Main
↓
根据 A 结果
↓
Research B
```

必须分阶段。

---

# 二十、不要做双层无限 fan-out

不要出现：

```text
Main
→ 5 Research Agents

每个 Research
→ 10 Tool calls
→ Search-again loops
```

这是典型 agent explosion。

正确的是：

```text
Main 控制 Topic fan-out
Research 内 bounded batch
```

---

# 二十一、当前代码建议最终收敛成三个层次

```text
schemas/
  ResearchRequest
  VerificationItem
  ResearchFindings

bounded_research.py
  Planner
  Host evidence execution
  Finalizer
  attestation

capabilities/research_agent.py
  Main-facing Agent-as-Tool adapter
```

旧的：

```text
build_research_agent()
iterative worker
```

应该明确：

```text
legacy only
```

最好最终迁到：

```text
legacy/iterative_research_agent.py
```

避免出现两个 Research Agent Source of Truth。

---

# 二十二、测试体系也应该跟着改

现在真正应该有的 eval 不是：

```text
模型能不能调用 research_agent
```

而是：

### Routing eval

```text
single current fact
→ Main

several predetermined independent facts
→ Main parallel

deterministic route feasibility
→ Main

bounded evidence-heavy Pass comparison
→ research_agent

Research A result creates new Research B
→ Research → Main → Research（path-dependence 属于 Main orchestration）
```

### Handoff eval

验证：

```text
objective 清晰
verification_items 非空
context minimal
constraints 正确
没有 queries/tool sequence
```

### Research eval

验证：

```text
每个 action 服务 verification item
不存在空 item_ids
bounded tool batch
每个 verification item 都有 result
```

### Context isolation eval

比较：

```text
Main Direct
vs
Main + Research

quality
tokens
latency
Main context growth
```

---

# 最终一句话定义

我认为我们现在可以正式把 `research_agent` 定义成：

> **一个由 Main 以 Agent-as-Tool 方式调用的、面向一个 bounded Research Topic 的 context-isolated evidence worker。单次调用不是自由 path-dependent agent：Main 传入 objective 与 atomic verification_items 定义 completion boundary，Planner 一次规划有限 evidence batch，Host 并行执行并读取权威来源，Finalizer 压缩为 ResearchFindings，Host 再做 item-scoped normalization 与全局 attestation 后返回。只有原始 evidence 会显著污染 Main 上下文、且最终结果能够高度压缩时才使用。真正的 Search→Observe→Search-again 动态探索属于 Main 的分阶段 orchestration（Research A → Main → Research B），不发生在 child 内。**

再压缩成架构口号就是：

```text
Main decides WHAT.

Research discovers HOW,
within a bounded scope.

Host owns reality.

Findings cross the context boundary.
```

这版我认为已经可以作为 `research_agent` 的正式架构设计基线。


- Anthropic — Building Effective Agents
  https://www.anthropic.com/engineering/building-effective-agents

- Anthropic — Multi-Agent Research System
  https://www.anthropic.com/engineering/multi-agent-research-system

- Anthropic — Effective Context Engineering for AI Agents
  https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

- OpenAI Agents SDK — Multi-Agent Orchestration
  https://openai.github.io/openai-agents-python/multi_agent/

- LangChain — Subagents
  https://docs.langchain.com/oss/python/langchain/multi-agent/subagents