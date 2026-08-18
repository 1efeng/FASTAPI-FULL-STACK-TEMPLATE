# Research Checklist 产品化施工方案

> 日期：2026-08-18
> 状态：✅ 已完成
> 适用：Travel Planning → Main → `research_agent` → Research Progress UI

## 1. 第一性原理目标

用户发起完整旅行规划后，需要持续知道：

1. 系统正在核验哪些真正影响方案成立的现实问题；
2. 哪些事实已经被可靠证据确认；
3. 哪些仍在核验；
4. 哪些无法可靠确认；
5. 当前系统仍在工作，而不是卡死。

因此 Research UI 的产品对象不是 tool event log，而是 **evidence-backed verification checklist**。

目标主链路：

```text
Candidate Plan
→ Reality Gaps
→ Research Topic
→ short title + atomic verification_items
→ research_agent 自主研究
→ real Search / Fetch / Maps / Weather evidence
→ Host evidence attestation
→ verification_results
→ ResearchFindings
→ Main revise
→ Checklist UI projection
```

## 2. 施工目标

### G1. Topic Handoff Contract

`ResearchRequest` 从：

```text
objective / context / constraints
```

扩展为：

```text
title
objective
verification_items[]
context
constraints
```

`title` 是短 UI 标题；`objective` 是完整决策问题。

`verification_items` 是原子验收项，不是搜索 query、tool sequence 或 reasoning steps。

示例：

```text
title: 北京核心景点开放、预约与门票
verification_items:
- palace-opening: 故宫博物院 / 开放与闭馆规则
- palace-reservation: 故宫博物院 / 预约渠道与放票规则
- palace-price: 故宫博物院 / 当前门票价格
- temple-opening: 天坛公园 / 开放规则
- temple-price: 天坛公园 / 当前门票价格
...
```

### G2. Evidence-backed Result Contract

`ResearchFindings` 增加 `verification_results[]`，每个 result 必须对应一个 input item。

只有经过 Host evidence attestation 的 result 才能为 `verified`。

```text
model says verified
→ filter observed source URLs / dedicated tool evidence
→ no surviving evidence
→ downgrade unresolved
```

遗漏的 verification item 由 Host 补成 unresolved，不能静默消失。

### G3. Research Scope Guard

Research Agent instructions 冻结：

```text
每一次 Search / Fetch / Maps / Weather 都必须直接服务至少一个 verification_item。
不会改变任何 verification_item 结论的调查必须停止。
```

例如：

```text
Topic = 郑州↔北京高铁票价/时长/班次
verification_items 不包含颐和园→北京西路线
→ research_agent 不应调用 Maps 去核验颐和园路线
```

### G4. Product Progress Contract

保留当前兼容字段：

```text
topic / status / stage / label
```

增量增加：

```text
topic_title
verification_items (topic start snapshot)
item_id / entity / aspect (item result event)
source (observable execution detail, optional)
```

旧/无 checklist 请求继续使用现有 Research progress fallback，不使请求失败。

### G5. Checklist-first UI

默认界面：

```text
正在研究并核验最新信息          2 个主题 · 42s

北京核心景点开放、预约与门票
6/11 已确认
  故宫博物院
    ✓ 开放/闭馆规则
    ◌ 预约渠道与放票规则
    · 当前门票价格
  天坛公园
    ...
  当前：正在读取 dpm.org.cn       ← Shimmer

郑州↔北京高铁票价与时刻
...
```

规则：

- Topic title：稳定文字，不 Shimmer；
- active execution detail：Shimmer；
- verified：✓；
- unresolved/conflicting：!；
- 未完成：中性 pending，不伪装为 ✓；
- 原始 Search/Fetch/Maps event history 默认折叠到“查看研究详情”。

## 3. 非目标

本轮不做：

- 新 Workflow engine；
- DynamicWorkflow 恢复为 production 主路径；
- Temporal / DBOS；
- 展示 chain-of-thought / 原始模型 reasoning；
- 把模型生成的 progress 文案当作 verified 状态；
- 重构 Product RequestRun / StreamResumeStore / PostgreSQL schema；
- 为了 UI 新增不必要的 LLM summarizer。

## 4. 验收标准

### A. Contract

- [x] `ResearchRequest` 支持短 `title` + atomic `verification_items`。
- [x] `ResearchFindings` 返回逐项 `verification_results`。
- [x] input item ID 与 result ID 可闭环；缺失项自动 unresolved。
- [x] production `research_agent` tool schema 可接收新字段。
- [x] 无 checklist 的旧请求仍可运行。

### B. Evidence / Correctness

- [x] `verified` verification result 没有真实 observed evidence 时被 Host 降级。
- [x] 未实际执行成功的 source/tool 不能产生 verified。
- [x] `ResearchFindings.sources` 继续只保留真实观察到的 URL。
- [x] Research Agent instructions 明确 tool call 必须服务 checklist。
- [x] Main Skill 明确动态精确事实只能来自 verified Findings 或 Main 自己真实工具结果。

### C. Progress

- [x] Topic start event 带短标题和 checklist snapshot。
- [x] Topic 完成前 UI 明确显示 running + elapsed time。
- [x] 完成后逐项显示 verified / conflicting / unresolved。
- [x] 不再出现 `✓ 正在读取...`、`✓ 正在核验...` 这种矛盾状态。
- [x] active step 使用 Shimmer。
- [x] 默认不铺满完整 event log。

### D. Availability / Regression

- [x] independent topics 仍可同一 Main turn 并行。
- [x] parent cancellation 仍传播到 children。
- [x] child recoverable failure 仍 topic-level unresolved，不拖死 sibling。
- [x] Product usage 仍聚合 Main + all research children。
- [x] existing streaming protocol / reconnect / terminal gate contract 不改变。
- [x] backend Agent suite 全绿。
- [x] backend full tests 无新增失败。
- [x] frontend TypeScript + production build 通过。
- [x] Ruff + 本轮改动范围 mypy/ty 通过。

## 5. 关键施工问答

### Q1. verification_items 会不会重新变成固定 Research Steps？

不会。它只回答“什么事实必须被证明”，不规定“怎么搜”。Research Agent 仍自主决定 Search / Read / Fetch / Maps / Compare 顺序。

### Q2. 为什么不让 Research Agent 自己播报 checklist 状态？

因为模型自报不能证明事实已经被核验。`checking` 可以是执行态，`verified` 必须经过 Host evidence attestation。

### Q3. 为什么需要短 title？

完整 objective 是 Agent contract，不是 UI copy。长 objective 会把研究面板变成日志墙，降低扫描效率。

### Q4. 为什么默认折叠 execution log？

用户关心“哪些事实已确认”，不是每次 model/search/fetch 循环。详细执行轨迹只用于解释和诊断，放到二级详情。

### Q5. Shimmer 放在哪里？

只放当前 active execution detail 和顶部运行态。Topic 标题、历史 completed item 不闪。

### Q6. 如何保持可用性？

新字段增量接入；无 checklist 时 fallback 到旧 progress；旧 DynamicWorkflow builder 保留 rollback；不修改 Product DB/API/stream ownership。

### Q7. 如何防止 Topic B 跑去查颐和园路线？

Main handoff 使用原子 verification_items 缩小 scope；Research instructions 要求每次 tool call 直接服务至少一项 checklist。后续若 live eval 仍出现明显漂移，再增加 Host tool-scope guard，不在第一步过度实现。

## 6. 施工步骤

### Stage 1 — Handoff / Findings Contract

1. 新增 `VerificationItem` / `VerificationResult`。
2. 扩展 `ResearchRequest` / `ResearchFindings`。
3. 扩展 direct `research_agent` tool schema。
4. 更新 travel-planning Skill handoff 规范。
5. 添加 schema / routing contract tests。

**Gate 1：contract tests + routing tests PASS 后再进入 Stage 2。**

### Stage 2 — Host Evidence Attestation + Progress Projection

1. `ResearchEvidenceTrace` 保存 request checklist metadata。
2. Host attestation 校验 `verification_results`。
3. 缺失 item 自动 unresolved。
4. topic start event 携带 checklist snapshot。
5. attested output 生成 item result events。
6. execution detail 继续只来自真实 runtime events。

**Gate 2：evidence/runtime tests PASS。**

### Stage 3 — Checklist-first Frontend

1. 前端解析新 progress payload。
2. Topic 用短标题。
3. Checklist 按 entity 分组。
4. 当前 active detail 用 Shimmer。
5. finished status 使用完成态文案，不给“正在...”加 ✓。
6. execution log 默认折叠。
7. 无 checklist payload fallback 到旧 UI。

**Gate 3：TypeScript + Vite build + frontend lint PASS。**

### Stage 4 — Regression / Product Gate

1. parallel research。
2. dependent research。
3. evidence isolation。
4. usage aggregation。
5. cancellation propagation。
6. child failure degradation。
7. streaming protocol。
8. backend full tests。
9. frontend production build。

**Gate 4：无新增 P0/P1，完成本轮。**

## 7. 验收结果

```text
Gate 1 — Handoff / Findings Contract
26 passed
Ruff PASS
mypy PASS

Gate 2 — Host Evidence / Progress
34 passed
Ruff PASS
mypy PASS
ty PASS

Gate 3 — Checklist-first Frontend
Biome PASS
TypeScript PASS
Vite production build PASS

Gate 4 — Product Regression
Agent suite: 107 passed
Backend full: 260 passed / 18 skipped
Ruff full: PASS
本轮范围 mypy: PASS
本轮范围 ty: PASS
git diff --check: PASS
```

## 8. 完成定义

本轮完成后，Research UI 应从：

```text
✓ 正在拆分核验项
✓ 已检索最新来源
```

变成：

```text
北京核心景点开放、预约与门票
6/11 已确认

故宫博物院
✓ 开放/闭馆规则
◌ 预约渠道与放票规则
· 当前门票价格

当前：正在读取 dpm.org.cn
```

同时 `✓` 必须代表 Host 已观察到证据，而不是“某个步骤曾经运行过”。
