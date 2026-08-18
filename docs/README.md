已经一次性写入完整文档体系，不再拆开逐个推进。

新增：

```text
docs/
├── product/
│   ├── travel-agent-product-architecture-v1.md   （已有）
│   └── travel-agent-product-spec-v1.md            （新增）
│
├── domain/
│   └── trip-context-model-v1.md                   （新增）
│
├── research/
│   └── research-question-schema-v1.md              （新增）
│
└── architecture/
    └── travel-agent-routing-v1.md                  （新增）
```

这几份现在形成完整闭环：

---

## 1. Product Spec

解决：

> 用户到底想从旅行中得到什么？

固定：

- 用户目标
- 同行关系
- 体验诉求
- 约束模型

避免以后 Agent 只看：

```text
地点 + 日期 + 人数 + 预算
```

---

## 2. Trip Context Model

解决：

> 一次旅行到底需要哪些上下文？

定义：

```text
User Intent
    ↓
Travelers
    ↓
Constraints
    ↓
Preferences
    ↓
Reality
    ↓
Risk
```

核心原则：

> 信息不是越多越好，只有会改变决策的信息才值得获取。

---

## 3. Research Question Schema

解决：

> Research Agent 到底研究什么？

冻结：

Research Agent ≠ 搜索助手

而是：

> 验证会改变旅行决策的不确定变量。

例如：

错误：

```text
研究北京旅游
```

正确：

```text
验证八达岭是否适合第三天返程
```

---

## 4. Routing Architecture

解决：

> Agent 怎么协作？

冻结流程：

```text
User
 ↓
Intent Understanding
 ↓
Candidate Planner
 ↓
Decision Gap Analyzer
 ↓
Research Router
 ↓
Reality Layer
 ↓
Evidence
 ↓
Final Planner
 ↓
Travel Plan
```

---

现在文档层面已经从：

之前：

```text
Agent
 ├ Search
 ├ Research
 ├ Skill
 └ Prompt
```

变成：

```text
产品目标
 ↓
领域模型
 ↓
决策缺口
 ↓
研究问题
 ↓
Agent Routing
 ↓
实现
```

后续 Cursor/Codex 改造应该基于这一套，而不是继续围绕旧 Research Agent 打补丁。

下一步可以开始做：

```
docs/architecture/
└── implementation-plan-v1.md
```

把这套设计映射到当前 `travel_agent_v8` 代码：

- 哪些保留
- 哪些删除
- 哪些重构
- 分阶段施工顺序

这个才是施工文档。