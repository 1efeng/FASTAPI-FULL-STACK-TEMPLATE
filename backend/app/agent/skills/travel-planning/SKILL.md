---
name: travel-planning
description: 创建、重新规划或修改完整旅行行程的专业旅行规划技能。适用于多日旅行规划、每日路线安排、行程调整、旅行节奏、交通与预算设计，以及已有完整行程的修改。仅当用户明确要求规划、安排、重新规划或修改完整旅行时使用；不要用于问候、闲聊、普通旅行问答、单个景点介绍、轻量推荐、单次天气、交通或开放时间查询。
---

# 旅行规划

生成真实可执行、路线合理、符合用户偏好的完整旅行计划。

Main Agent 始终是 Research Leader、最终决策者、最终规划者和最终回答者。
本 Skill 只提供规划方法、Research Need 判断和输出规范。

## 1. 先理解真正影响方案的条件

关注：
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

## 2. Research Need

判断标准是：最终方案是否依赖需要当前外部世界核验的信息，而不是单纯看天数或城市数量。

### Research Need YES

满足任一：
1. 依赖当前 / 最新 / 官方事实：开放、闭馆、预约、门票 / Pass、运营政策、交通规则、施工 / 临时关闭；
2. 用户要求“真正能执行 / 查最新 / 查官方 / 确认预约 / 按实际情况”；
3. 需要比较当前交通 / Pass / 票价 / 路线现实时间；
4. 与实际旅行日期直接相关的天气、季节运营、节假日规则或近期交通变化；
5. Main 无法只靠用户信息 + 稳定常识可靠完成关键决策。

### Research Need NO

- 灵感 / brainstorm；
- rough draft / 框架；
- 用户明确说不用查最新 / 不联网 / 先做草案；
- 只要区域组合、路线思路、节奏建议；
- 用户已经提供足够事实，只需重组。

## 3. Research 选择：Quick vs Deep

Research Need YES 不代表一定启动 Deep Research。

### Quick Research

只有一个清晰研究轴时，Main 直接使用模型原生 `WebSearch` 能力，以及需要的 `web_fetch`、`search_maps`、`get_weather`。

例如：
- 一个景点的最新预约规则；
- 单条城际路线；
- 某天的天气；
- 一个景点图片请求。

不要为单个事实开 Deep Research。

### Parallel Deep Research

完整计划存在 2~3 个真正独立、可并行的 research axes 时才使用。

流程：

`Main → load deep-research → run_workflow once → research_worker × 2~3 parallel → structured ResearchFindings → Main synthesis → Budget / FX → Markdown Contract → Final`

Main 自己就是 Leader，不创建 Lead Researcher / Supervisor。

Deep Research v1 规则：
- 同一用户请求最多一次 `run_workflow`；
- 总 Worker 调用 hard cap = 3；
- 只做一层 fan-out；
- Worker 不调用 Worker；
- Worker 不拥有 `run_workflow`；
- 不做自动第二轮 Research；
- topic 必须独立、non-overlapping、self-contained。

典型复杂旅行拆分：
1. 景区开放 / 预约 / 门票 + 关键 POI 展示图片；
2. 城际 / 关键市内交通；
3. 旅行日期天气 / 行程风险。

## 4. Workflow 编排规则

workflow 内应真正并行：使用 `asyncio.gather(...)` 调用多个 `research_worker(task=...)`，不要串行等待。

Harness sandbox 不支持 `return_exceptions=True`。需要部分失败不拖垮全批时，用 async wrapper：
- wrapper 内 `try: await research_worker(...)`；
- `except RuntimeError:` 返回一个明确的 unavailable/unresolved 结果；
- gather wrapper calls；
- 最后一行返回结果列表，不用 `print()` 承载结构化结果。

Worker 失败后 Main 不启动第二个 workflow，不用模型记忆补当前事实。

## 5. Research Task 必须自包含

每个 task 至少说明：
- Runtime 当前日期、年份、时区；
- 旅行背景和实际相关日期；
- 用户关键约束；
- 一个明确 research topic；
- freshness / official-source 要求；
- Anti-confirmation：不得把猜测写进 Query 当事实；
- 若 topic 涉及最终展示 POI，允许发现少量 media；
- 只返回 ResearchFindings，不生成最终 itinerary。

## 6. Research 新鲜度与证据

对门票、预约、开放、运营、交通规则、节假日特殊安排等动态事实：
- 以 Runtime 时间为基准；
- 优先 latest / current / official；
- 重要动态事实优先 official / primary source；
- 模型原生 `WebSearch` 用于 discovery，关键事实尽量用 `web_fetch` 页面正文；
- 第三方旅行平台主要用于比较、评论和补充；
- 旧资料不能直接当当前事实；
- 无法可靠确认则 unresolved；
- 不构造确认性 Query 自证模型猜测。

`get_weather` 和 `search_maps` 是专用事实 Tool；图片搜索不是事实验证 Tool。

## 7. 图片 / Media

模型原生 `WebSearch` 可以发现与景区、POI、地标、酒店或特色体验相关的网页和来源；当前不再提供独立的 SearXNG 图片搜索工具。

规则：
- 搜索来源可用于辅助展示素材发现，但不保证返回可直接展示的图片 URL；
- 图片来源不能证明开放、预约、门票、交通政策、价格或天气；
- 纯天气、纯交通、纯政策 Research 不要无意义搜索图片；
- 不做图片下载、CDN、转存或版权授权判断。

## 8. 路线可执行性

优先：
- 同区域集中；
- 减少跨区往返；
- 避免明显回头路；
- 控制每天长距离移动；
- 给交通、排队、吃饭、休息留真实时间；
- 根据旅行者调整强度；
- 保留必要缓冲。

结合可靠 Findings 检查开放 / 最晚入场 / 闭馆日 / 预约 / 天气 / 抵返时间 / 城际交通 / 排队时间。
不得生成明显冲突的行程。

## 9. 预算

根据预算调整住宿、城际交通、当地交通、景点体验、餐饮和其他消费。

- 没有可靠价格时使用区间或明确规划预留；
- 不编造未经核验的精确金额；
- `calculate_budget` 只汇总最终采用方案；
- 不把未采用备选价格混入最终预算；
- 计算器不能把未核验价格变成事实；
- 金额必须写明币种，不用裸 `¥`；
- 事实价保留当地货币；需要辅助换算时才用 `convert_currency`。

## 10. 创建完整计划

1. 理解用户需求和 slot。
2. 缺少会改变整体方案的关键条件时先简洁澄清。
3. 读取本 Skill。
4. 判断 Research Need。
5. Research Need NO：Main 直接选定方案。
6. Research Need YES 且只有一个 axis：Main Quick Research。
7. Research Need YES 且有 2~3 个独立 axes：加载 `deep-research`，调用一次 `run_workflow` 并行研究。
8. Main 根据用户约束 + 可靠 Findings 做最终路线 / 交通 / 住宿 / 每日节奏决策。
9. 涉及多项费用时用 `calculate_budget`；需要时用 `convert_currency`。
10. 读取 `references/markdown-contract.md`。
11. 严格按 Markdown Contract 输出完整计划。

如果 Research 部分失败：使用成功 Findings + 用户事实 + 稳定常识 + 明确假设继续；动态未核验项必须标记，不得编造精确事实。

## 10.1 对外表达边界

最终回答不得暴露内部执行过程。不要提及或复述 Skill、Capability、SubAgent、Worker、workflow、Tool 名称、工具参数、原始搜索词、模型 / provider、重试或预算限制。

不要逐步播报工具调用。需要表达进展时，只使用自然产品语义，例如“正在核对最新规则”“正在比较路线”“正在整理方案”。

最终只输出用户需要的结论、必要依据、来源和不确定性，不输出内部调试信息或框架事件。

## 11. 修改已有计划

将 conversation 中最近一版完整计划视为当前版本：
- 保留未被修改的约束和有效安排；
- 对受影响部分重新判断 Research Need；
- 单一新事实用 Quick Research；多个独立动态轴才使用一次 Deep Research；
- 重新检查路线、时间和预算连锁影响；
- 最终返回新的完整计划，而不是 diff / patch。

## 12. 最终质量检查

输出前确认：
- 最新用户要求和预算口径正确；
- Runtime 时间使用正确；
- Research 路径选择正确，没有为单一事实滥用 Deep Research；
- 同一请求没有第二次 `run_workflow`；
- Worker Findings 与 Main 最终决策职责没有混淆；
- 天数、路线、交通时间和抵返时间合理；
- 开放 / 预约 / 天气等动态约束基于可靠证据或明确 unresolved；
- 图片只作 media，不作事实证据；
- 没有用猜测自证；
- 预算只汇总最终采用方案；
- 没有伪造当前精确事实；
- 最终结果是完整旅行计划。

不要创建额外 Validator Agent / Validator Workflow。
