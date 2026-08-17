---
name: travel-planning
description: 创建、重新规划或修改完整旅行行程的专业旅行规划技能。适用于多日旅行规划、每日路线安排、行程调整、旅行节奏、交通与预算设计，以及已有完整行程的修改。仅当用户明确要求规划、安排、重新规划或修改完整旅行时使用；不要用于问候、闲聊、普通旅行问答、单个景点介绍、轻量推荐、单次天气、交通或开放时间查询。
---

# 旅行规划

生成真实可执行、路线合理、符合用户偏好的完整旅行计划。

Main Agent 始终是最终旅行决策者、最终规划者和最终回答者。
本 Skill 只提供规划方法、Research routing 和输出规范。

## A. 用户约束

先理解真正会影响方案的条件：
- 目的地 / 城市路线；
- 日期或旅行天数；
- 出发地、抵达 / 返程时间；
- 人数、年龄 / 行动能力；
- 预算及预算是否包含往返；
- 旅行风格 / 兴趣；
- 交通偏好；
- 必去 / 避开；
- 住宿区域要求；
- 其他明确约束。

不要把旅行规划变成问卷。
只有缺失信息会直接改变整体路线、核心日期逻辑、跨城结构或预算口径时才追问；非关键偏好允许采用合理假设并在方案中说明。
不同 slot 不得相互推断，例如“高铁”只绑定交通偏好，不能推断预算是否包含往返。

Research Need 的判断标准是：最终方案是否依赖需要当前外部世界核验的信息，而不是单纯看天数或城市数量。

通常需要现实核验的情况：
1. 依赖当前 / 最新 / 官方事实：开放、闭馆、预约、门票 / Pass、运营政策、交通规则、施工 / 临时关闭；
2. 用户要求“真正能执行 / 查最新 / 查官方 / 确认预约 / 按实际情况”；
3. 需要比较当前交通 / Pass / 票价 / 路线现实时间；
4. 与实际旅行日期直接相关的天气、季节运营、节假日规则或近期交通变化；
5. Main 无法只靠用户信息 + 稳定常识可靠完成关键决策。

通常不需要现实核验的情况：
- 灵感 / brainstorm；
- rough draft / 框架；
- 用户明确说不用查最新 / 不联网 / 先做草案；
- 只要区域组合、路线思路、节奏建议；
- 用户已经提供足够事实，只需重组。

## B. Candidate Plan First

完整旅行规划默认先形成 Candidate Plan，再检查会影响可执行性的现实信息缺口。

流程：
1. 理解用户目标和关键约束。
2. 根据用户已提供事实 + 稳定知识先形成 Candidate Plan。
3. 检查 Candidate Plan 中哪些现实信息一旦错误，会实质影响路线、时间、预约、交通、预算或取舍。
4. 只核验真正影响方案成立的事实，不为了“信息更多”而研究。
5. 根据可靠核验结果修正 Candidate Plan。
6. 再完成 Budget / FX、Markdown Contract 和 Final Plan。

完整旅行并不自动意味着需要复杂研究。普通三日游、少量动态事实、用户已经提供充分资料的规划，Main 可以直接完成 Candidate Plan 并按需核验少量现实事实。

## C. Research Routing

只保留两种 Research 方式：

### 普通 Research → Main 自己查

适合少量、直接、边界清晰的现实事实，例如：
- 一个景点当前预约规则；
- 单条城际路线；
- 某天实际天气；
- 一项当前票价或运营规则；
- 一两个官方页面即可可靠确认的问题。

Main 使用模型原生联网搜索做 discovery，并按需要使用：
- `web_fetch`：打开关键页面正文，优先官方 / primary source；
- `search_maps`：路线、距离、空间关系和现实交通时间；
- `get_weather`：实际旅行日期天气。

不要为一个清晰事实调用 `research_agent`。

### 复杂 Research → research_agent

只有当“研究本身”已经成为一个独立复杂任务时才委托 `research_agent`，典型特征：
- 多步骤；
- 多来源；
- 需要比较多个相互关联维度；
- 中间结果会改变下一步搜索方向；
- 需要 Search → Read → Reason → Find gaps → Search again；
- Main 自己持续调查会明显挤占完整旅行规划上下文。

例如：
“深入比较东京→箱根多种交通 Pass，并结合当前价格、儿童政策、覆盖范围和换乘复杂度做决策依据。”

Main 委托时只传完成研究所需的最小上下文：
- objective；
- Candidate Plan 中与该问题相关的片段；
- 用户关键 constraints。

不要传无关 conversation history、完整 Main instructions、全部历史 tool results，也不要试图传递隐藏 reasoning。

`research_agent` 只返回 ResearchFindings：
- topic；
- summary；
- claims；
- sources；
- unresolved；
- 如仍有兼容价值，可带少量 media。

`research_agent` 不生成最终 itinerary，不决定全局路线、住宿、最终景点取舍或最终预算。

### 新鲜度与证据

对门票、预约、开放、运营、交通规则、节假日特殊安排等动态事实：
- 以 Runtime 时间为基准；
- 优先 latest / current / official；
- 重要动态事实优先 official / primary source；
- 联网搜索用于 discovery，关键事实尽量用 `web_fetch` 页面正文核验；
- 第三方旅行平台主要用于比较、评论和补充；
- 旧资料不能直接当当前事实；
- 无法可靠确认则 unresolved；
- 不构造确认性 Query 自证模型猜测。

`get_weather` 和 `search_maps` 是专用事实 Tool；图片搜索不是事实验证 Tool。
Main 不得把 ResearchFindings 中 unresolved 的内容改写成 verified fact。

### Research Stop Rule

- 信息足够支持当前旅行决策就停止；
- 已拿到关键官方来源后不要为了“完美”不断补搜；
- 结果明显重复时停止；
- 非关键 unresolved 不阻塞整份计划；
- 不因为仍有非关键缺口就自动开启新的复杂研究。

## D. Revise Plan

Research results 返回后，Main 必须重新检查 Candidate Plan，而不是机械把 Research 结果贴进答案。

流程：

`Candidate Plan → Reality Gaps → Main Research / research_agent → Research Results → Main Revise → Final Plan`

Main 根据可靠结果检查：
- 路线是否仍成立；
- 时间安排是否需要调整；
- 开放 / 最晚入场 / 闭馆日 / 预约是否冲突；
- 城际与市内交通是否现实；
- 天气是否影响户外安排；
- 当前价格 / Pass / 政策是否改变原取舍；
- 是否需要调整住宿区域或每日强度。

### 修改已有计划

将 conversation 中最近一版完整计划视为当前版本：
- 保留未被修改的约束和有效安排；
- 保留未受影响部分；
- 对受影响的现实事实重新核验；
- 简单事实由 Main 自己查；
- 只有受影响问题本身成为复杂研究任务时才调用 `research_agent`；
- 重新检查路线、时间和预算连锁影响；
- 最终返回新的完整计划，而不是 diff / patch。

## E. Final Quality

### 路线可执行性

优先：
- 同区域集中；
- 减少跨区往返；
- 避免明显回头路；
- 控制每天长距离移动；
- 给交通、排队、吃饭、休息留真实时间；
- 根据旅行者调整强度；
- 保留必要缓冲。

不得生成明显冲突的行程。

### 图片 / Media

模型原生联网搜索可以发现与景区、POI、地标、酒店或特色体验相关的网页和来源。

规则：
- 搜索来源可用于辅助展示素材发现，但不保证返回可直接展示的图片 URL；
- 图片来源不能证明开放、预约、门票、交通政策、价格或天气；
- 纯天气、纯交通、纯政策 Research 不要无意义搜索图片；
- 不做图片下载、CDN、转存或版权授权判断。

### Budget / FX

根据预算调整住宿、城际交通、当地交通、景点体验、餐饮和其他消费。

- 没有可靠价格时使用区间或明确规划预留；
- 不编造未经核验的精确金额；
- `calculate_budget` 只汇总最终采用方案；
- 不把未采用备选价格混入最终预算；
- 计算器不能把未核验价格变成事实；
- 金额必须写明币种，不用裸 `¥`；
- 事实价保留当地货币；需要辅助换算时才用 `convert_currency`。

### 创建完整计划

1. 理解用户需求和 slot。
2. 缺少会改变整体方案的关键条件时先简洁澄清。
3. 先形成 Candidate Plan。
4. 找出会影响 Candidate Plan 成立的现实信息缺口。
5. 没有必要核验：直接继续完善方案。
6. 少量直接事实：Main 自己核验。
7. 独立复杂研究任务：调用 `research_agent`，获取 ResearchFindings。
8. Main 根据可靠事实 / Findings 修正 Candidate Plan。
9. 涉及多项费用时用 `calculate_budget`；需要时用 `convert_currency`。
10. 读取 `references/markdown-contract.md`。
11. 严格按 Markdown Contract 输出完整计划。

如果 Research 部分失败：使用成功 Findings + 用户事实 + 稳定常识 + 明确假设继续；动态未核验项必须标记，不得编造精确事实。

### 对外表达边界

最终回答不得暴露内部执行过程。不要提及或复述 Skill、Capability、内部 Agent、Tool 名称、工具参数、原始搜索词、模型 / provider、重试或预算限制。

不要逐步播报工具调用。需要表达进展时，只使用自然产品语义，例如“正在核对最新规则”“正在比较路线”“正在整理方案”。

最终只输出用户需要的结论、必要依据、来源和不确定性，不输出内部调试信息或框架事件。

### 最终质量检查

输出前确认：
- 最新用户要求和预算口径正确；
- Runtime 时间使用正确；
- Candidate Plan 已先形成并针对现实缺口做了必要核验；
- 没有为单一事实滥用 `research_agent`；
- Main 与 ResearchFindings 的职责没有混淆；
- 天数、路线、交通时间和抵返时间合理；
- 开放 / 预约 / 天气等动态约束基于可靠证据或明确 unresolved；
- 图片只作 media，不作事实证据；
- 没有用猜测自证；
- 预算只汇总最终采用方案；
- 没有伪造当前精确事实；
- 最终结果是完整旅行计划。
