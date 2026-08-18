---
name: travel-planning
description: 创建、重新规划或修改完整旅行行程的专业旅行规划技能。适用于多日旅行规划、每日路线安排、行程调整、旅行节奏、交通与预算设计，以及已有完整行程的修改。仅当用户明确要求规划、安排、重新规划或修改完整旅行时使用；不要用于问候、闲聊、普通旅行问答、单个景点介绍、轻量推荐、单次天气、交通或开放时间查询。
---

# 旅行规划

生成真实可执行、路线合理、符合用户约束的完整旅行计划。

Main 始终是最终用户意图负责人、最终旅行决策者和最终回答者。本 Skill 是 Travel Planning 领域流程、Research routing、路线质量、预算处理和输出规范的 Source of Truth。

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

不要把旅行规划变成问卷。只有缺失信息会直接改变整体路线、核心日期逻辑、跨城结构或预算口径时才追问；非关键偏好允许采用合理假设并在方案中说明。

不同 slot 不得相互推断，例如“高铁”只绑定交通偏好，不能推断预算是否包含往返。

## B. Candidate Plan First

完整旅行规划默认先形成 Candidate Plan，再决定需要研究什么。

流程：
1. 理解用户目标、关键约束和必须满足的 slot。
2. 使用用户已提供事实 + 稳定知识先形成 Candidate Plan，包括大致城市 / 每日结构、区域组合、主要移动和旅行节奏。
3. 不要在 Candidate Plan 之前为了“信息更多”而搜索所有景点、价格、交通或政策。
4. 检查 Candidate Plan 中哪些现实信息一旦错误，会实质影响路线、时间、预约、交通、预算或重要取舍；这些是 Reality Gaps。
5. 判断每个 Reality Gap 是孤立事实，还是应与其他相关 Gap 聚合成一个 Research Topic。
6. 完成必要核验后，由 Main 修正 Candidate Plan。
7. 再完成 Budget / FX、Markdown Contract 和 Final Plan。

Research Need 的判断标准是：最终方案是否依赖需要当前外部世界核验的信息，而不是单纯看天数或城市数量。

通常需要现实核验的情况：
- 当前 / 最新 / 官方的开放、闭馆、预约、门票 / Pass、运营政策、交通规则、施工 / 临时关闭；
- 用户要求“真正能执行 / 查最新 / 查官方 / 确认预约 / 按实际情况”；
- 当前交通 / Pass / 票价 / 路线现实时间会改变方案；
- 与实际旅行日期相关的天气、季节运营、节假日规则或近期交通变化；
- Main 无法只靠用户信息 + 稳定常识可靠完成关键决策。

通常不需要现实核验的情况：
- 灵感 / brainstorm；
- rough draft / 框架；
- 用户明确说不用查最新 / 不联网 / 先做草案；
- 只需要区域组合、路线思路、节奏建议；
- 用户已经提供足够事实，只需重组。

## C. Reality Gap 与 Research Topic

### Reality Gap

Reality Gap 是 Candidate Plan 中一个会影响可执行性或重要取舍的现实未知项，例如：
- 某景点在旅行日期是否开放 / 是否需要预约；
- 某段交通是否现实可达、能否与返程衔接；
- 当前票价 / Pass 规则是否改变预算和方案；
- 某日天气是否会破坏关键户外安排。

### Research Topic

Research Topic 必须是一个明确的旅行决策问题，不是一个城市或目的地事实调查。
它可以聚合多个语义相关 Reality Gaps，但这些 gaps 必须共同影响同一个决策结论。

注意：不要因为某个 topic 是"可行性判断"就默认 delegate。如果：
- 开放；
- 预约；
- 路线；
- 交通；
- 时间余量；

这些查询在开始前已经可以明确规划，则 Main Direct / parallel tools 即可。

真正适合 research_agent 的 Topic 是 bounded evidence-heavy 对比或核验，例如：
- “结合东京、箱根、京都、大阪、广岛 10 日路线，比较全国 JR Pass、区域 Pass 与单买组合，核验价格、覆盖范围和关键组合，返回压缩比较结果”。

一个 Topic 可以包含多个相关事实，但必须有一个统一、可回答的 decision objective。
如果某个事实不会改变这个 decision，就不属于该 Topic。

核心职责：

**Main 拆 Research Topic；research_agent 把 Topic 压缩成一个最小、bounded 的 evidence batch。**

Main 负责决定“需要弄清楚什么”，不要预先写 query 或 Tool 顺序。research_agent 的职责不是自由循环探索，而是隔离高上下文成本：先规划最少证据调用，Host 并行执行，再把实际证据压缩成 ResearchFindings。证据仍不足时返回 unresolved，不通过 Search-again 无限扩张上下文。如果后续发现新的 Topic（例如新的区域 Pass 候选），由 Main 生成新的 Research Topic，不是 child 自己无限 Search-again。

## D. Research Routing

只保留两种现实核验路径：能由 Main 用一轮或少量并行 Tool 解决的事实由 Main 自己处理；只有确实值得隔离 evidence context 的主题级调查才调用 `research_agent`。

### 1. Isolated Fact → Main 自己核验

适合答案边界明确、查询集合在执行前就能确定的现实事实；不要求只能有一个事实。例如：
- 一个景点当前预约或开放规则；
- 一条城际 / 市内路线；
- 某天实际天气；
- 一项当前票价或运营规则；
- 一个清晰问题，一两次查询 / 读取通常即可可靠确认；
- 多个彼此独立、可以在同一模型响应中并行查询的开放时间 / 票价 / POI 等事实。

Main 可按需要使用：
- `search_poi`：按名称/关键词查地点 ID、坐标、地址和基础商业信息；
- `get_poi_detail`：查单个 POI 的评分、人均、电话、营业时间、入口和少量图片；
- `search_nearby`：按坐标查附近餐厅、酒店、景点等结构化 POI；
- `search_web`：发现当前政策、预约、公告等信息和候选来源，并保留 Host 可验证的来源 URL；
- `web_fetch`：打开关键页面正文，优先 official / primary source；
- `search_maps`：路线、距离、空间关系和现实交通时间；
- `get_weather`：实际旅行日期天气。

POI 工具适合地点、商业、位置和营业信息；预约、放票、临时闭馆、政策等动态规则不得仅凭 POI 数据确认，仍需 Web/官方来源核验。附近候选筛选通常用 `search_poi` 获取中心点后调用一次 `search_nearby`；若返回的 distance/rating/cost 已能完成筛选，不要再逐个查询 POI detail 或路线。只有决策确实缺少营业时间、入口、电话或真实路线耗时时才追加对应 Tool。

不要为一个孤立事实调用 research_agent；也不要因为“要查 3~5 个独立事实”就自动委托 child。能预先确定查询集合时，优先 Main 并行 Tool Calls，避免额外 planner/finalizer 模型开销。

Tool 数量 ≠ Agentic Complexity。即使需要 3 个 Search、2 个 Maps、多个 POI，只要 queries/tools 可以提前确定且 evidence 不重，仍应 Main parallel tools。

### 2. Research Topic → research_agent

当 Candidate Plan 暴露出一个需要隔离较多外部 evidence、直接塞进 Main 会明显膨胀后续上下文的决策问题时，Main 将会改变该决策的 Reality Gaps 聚合成一个 bounded objective，委托给 `research_agent`。

`research_agent` 的价值必须来自 context isolation + compression，而不是“Agent 层级更多”。如果 Main 用少量并行 Tool 就能解决，禁止为了形式上的多智能体而委托 child。

不要因为某个城市或行程“信息很多”就启动事实普查。如果多个相关 Reality Gaps 共同决定 Candidate Plan 某一部分是否成立，它们才应被视为一个 Research Topic。

只有符合以下条件时才使用单次 `research_agent`：
- Topic 是一个 bounded coherent decision problem；
- Main 能定义 atomic verification_items；
- evidence batch 可以由 Planner 一次规划；
- raw evidence 较重，值得隔离出 Main context；
- Findings 可以高度压缩。

注意：“复杂 feasibility question = research_agent”不成立。如果开放、预约、路线、交通、时间余量等查询在开始前已经可以明确规划，则 Main Direct / parallel tools 即可。

正确（bounded evidence-heavy 对比研究）：
“结合东京、箱根、京都、大阪、广岛 10 日路线，比较全国 JR Pass、区域 Pass 与单买组合，核验价格、覆盖范围和关键组合，返回压缩比较结果。”

错误的宽泛 Topic：
“调查北京核心景点的预约、开放、门票、暑期政策。”

错误拆法：
- research_agent(查故宫票价)
- research_agent(查故宫预约)
- research_agent(查故宫几点关门)

这些属于同一主题时应合并为一次 Topic 调查。

### 3. 一次规划允许 0..N 个 Research Topics

Main 每次完整规划可以调用 0..N 次 `research_agent`，不预先限定固定 Topic 数量。

一个独立 Research Topic 通常对应一次 `research_agent` 调用。不要为了控制调用次数把完全无关的主题强行塞进一个 objective，也不要把一个主题切成大量微型 Agent。

### 4. 独立 Topics 并行；有依赖 Topics 分阶段

如果 Candidate Plan 中存在多个彼此独立的 Research Topics，Main 应在同一个模型响应中发出多个 `research_agent` tool calls，由运行时并行执行，避免无意义串行等待。

例如：
- Topic A：北京核心景点预约 / 开放执行条件；
- Topic B：郑州↔北京 + 八达岭交通执行条件。

A 与 B 不互相依赖，可以同轮派发。

如果 Topic B 的定义取决于 Topic A 的结果，则必须分阶段：
Research A → Main 判断结果 → 再决定是否产生 / 派发 Research B。

例如：
Research A 比较全国 JR Pass 对完整路线的适用性（price / coverage）；Findings 显示关西段覆盖不理想；Main 据此产生新 Reality Gap，再派发 Research B 研究关西段是否有更合适的区域 Pass。

注意：故宫预约这类单个当前事实属于 Main Direct，不构成 Research Topic；也不要用它来演示分阶段依赖。

不要为了并行而并行，也不要在已有 Findings 足够时重复研究同一主题。

### 5. Research Handoff Contract

Main 委托 `research_agent` 时传一个面向决策的最小 contract：
- title：供产品 UI 展示的短标题，简洁概括 Topic，不直接复制完整 objective；
- objective：需要弄清楚的完整 Research Topic；
- verification_items：会改变该 Topic 决策结论的原子验收项；
- context：Candidate Plan 中与该主题直接相关的最小片段；
- constraints：会改变研究判断的用户关键约束。

`verification_items` 只定义“必须从外部世界证明什么”，不定义“怎么查”。每个 item 使用稳定 id，并包含 entity / aspect / question；不要把搜索词、工具顺序或 reasoning step 塞进 item。由已核验事实直接推导出的安全余量、是否值得、最终取舍等结论不应单独成为 verification item，避免为了派生结论再次搜索。

示例：
- `palace-opening`：故宫博物院 / 开放与闭馆规则 / 指定日期是否开放、固定闭馆日是什么；
- `palace-reservation`：故宫博物院 / 预约与放票 / 预约渠道、提前天数、放票时间；
- `palace-price`：故宫博物院 / 当前门票价格 / 指定日期适用的当前票价。

同一 Topic 下有多个景点或多个事实维度时，必须把它们拆成足够原子的 verification items，使某一项能明确落到 verified / conflicting / unresolved，而不是只给一个“景点规则已核验”的大项。

不要传：
- 无关 conversation history；
- 与 verification items 无关的 Candidate Plan 细节；
- 完整 Main instructions；
- 全部历史 tool results；
- 隐藏 reasoning；
- 预先写好的搜索步骤、query 列表、worker 数量或 research axes。

research_agent 只返回 ResearchFindings，且必须先回答 decision objective：
- topic；
- summary；
- verification_results：逐项对应 input verification_items；
- claims；
- sources；
- unresolved；
- 如仍有兼容价值，可带少量 media。

如果传入了 verification_items，每个 item 都必须有一条 verification result；没有可靠证据时必须 unresolved，不能静默省略，也不能新增 checklist 外的 result。

research_agent 不生成最终 itinerary，不决定全局路线、住宿、最终景点取舍或最终预算，不调用其他 Agent，也不能调用自身。生产 research_agent 固定为 bounded context compressor：1 次 Planner → Host 并行 evidence batch → authoritative Web 的首个权威来源可由 Host fetch → 1 次 Finalizer；不开放自由迭代 Tool Loop。

## E. Research 新鲜度与证据

对门票、预约、开放、运营、交通规则、节假日特殊安排等动态事实：
- 以 Runtime 时间为基准；
- 优先 latest / current / official；
- 重要动态事实优先 official / primary source；
- `search_web` 主要用于 discovery，关键事实尽量用 `web_fetch` 页面正文核验；
- 第三方旅行平台主要用于比较、评论和补充；
- 旧资料不能直接当当前事实；
- 无法可靠确认则 unresolved；
- 不构造确认性 Query 自证模型猜测。

`get_weather` 和 `search_maps` 是专用事实 Tool；图片搜索不是事实验证 Tool。

Main 不得把 ResearchFindings 中 unresolved 的内容改写成 verified fact。可靠来源互相冲突时保留 conflicting / uncertainty，由 Main 决定如何影响方案，不得伪装成确定事实。

最终答案中的动态精确事实（当前价格、具体开放时间、预约提前天数/放票时间、具体班次/时刻、当前政策等）必须来自 verified verification result / verified claim，或来自 Main 本轮自己真实成功执行的事实 Tool；不得根据模型记忆或 Candidate Plan 草案补写新的精确值。

### Research Stop Rule

- 一个 research_agent 调用只有一个 bounded evidence batch，不允许在 child 内反复 discovery；
- batch 证据足够则 verified / conflicting；不足则 unresolved，直接返回 Main；
- 非关键 unresolved 不阻塞整份计划；Main 根据它决定降级方案、采用保守假设，或在确实出现新的 decision-critical Topic 时再委托一次新研究；
- 当 ResearchFindings 已充分回答同一 scope 时，Main 应避免无意义重复调查；只有 conflicting / unresolved、新 evidence 或新出现的 decision-critical Reality Gap 才允许继续查；
- 不得为了“资料更完整”追加搜索，也不得把同一 Topic 换 query 重跑。

## F. Revise Candidate Plan

Research / Main fact results 返回后，Main 必须重新检查 Candidate Plan，而不是机械把结果贴进答案。

流程：

`Candidate Plan → Reality Gaps → Isolated Facts / Research Topics → Findings → Main Revise → Final Plan`

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
- 单个孤立事实由 Main 自己查；
- 受影响部分形成 Research Topic 时直接调用一个或多个 `research_agent`；
- 重新检查路线、时间和预算连锁影响；
- 最终返回新的完整计划，而不是 diff / patch。

## G. 路线与旅行质量

优先：
- 同区域集中；
- 减少跨区往返；
- 避免明显回头路；
- 控制每天长距离移动；
- 给交通、排队、吃饭、休息留真实时间；
- 根据旅行者年龄、行动能力和偏好调整强度；
- 抵达日和返程日给交通留缓冲；
- 不为塞更多 POI 牺牲可执行性。

不得生成明显冲突的行程。

## H. Weather / Maps / Media

### Weather

只有实际旅行日期天气会影响计划时才查。超出可靠预报范围时，不伪造精确逐日天气；可使用季节性常识做明确标注的规划假设，并说明临近出发需要再确认。

### Maps

`search_maps` 用于现实路线、距离、空间关系和交通时间判断。地图事实应服务于 Candidate Plan 的可执行性，不为无关 POI 做大量查询。

### Media

模型原生联网搜索可以发现与景区、POI、地标、酒店或特色体验相关的网页和来源，但不保证返回可直接展示的图片 URL。

规则：
- media 只服务展示；
- 图片来源不能证明开放、预约、门票、交通政策、价格或天气；
- 纯天气、纯交通、纯政策 Research 不要无意义搜索图片；
- 不做图片下载、CDN、转存或版权授权判断。

## I. Budget / FX

根据用户预算调整住宿、城际交通、当地交通、景点体验、餐饮和其他消费。

- 没有可靠价格时使用区间或明确规划预留；
- 不编造未经核验的精确金额；
- `calculate_budget` 只汇总最终采用方案；
- 不把未采用备选价格混入最终预算；
- 计算器不能把未核验价格变成事实；
- 金额必须写明币种，不使用可能产生歧义的裸 `¥`；
- 事实价保留当地货币；需要辅助换算时才用 `convert_currency`；
- `convert_currency` 只换算已确认金额，换算失败时保留当地货币，不猜汇率。

## J. 创建完整计划

1. 理解用户需求和关键 slot。
2. 缺少会改变整体方案的关键条件时先简洁澄清。
3. 先形成 Candidate Plan。
4. 从 Candidate Plan 找 Reality Gaps。
5. 不需要现实核验：继续完善方案。
6. 单个孤立事实：Main 自己核验。
7. 将相关 Reality Gaps 聚合成一个或多个 Research Topics。
8. 独立 Topics 在同一个模型响应中并行调用多个 `research_agent`；存在依赖的 Topics 分阶段调用。
9. Main 根据可靠 Facts / ResearchFindings 修正 Candidate Plan。
10. 涉及多项费用时用 `calculate_budget`；需要时用 `convert_currency`。
11. 读取 `references/markdown-contract.md`。
12. 严格按 Markdown Contract 输出完整计划。

如果 Research 部分失败：使用成功 Findings + 用户事实 + 稳定常识 + 明确假设继续；动态未核验项必须标记，不得编造精确事实。

## K. 对外表达边界

最终回答不得暴露内部执行过程。不要提及或复述 Skill、Capability、内部 Agent、Tool 名称、工具参数、原始搜索词、模型 / provider、重试或预算限制。

不要逐步播报工具调用。需要表达进展时，只使用自然产品语义，例如“正在核对最新规则”“正在比较路线”“正在整理方案”。

最终只输出用户需要的结论、必要依据和不确定性，不输出内部调试信息或框架事件。

## L. 最终质量检查

输出前确认：
- 最新用户要求和预算口径正确；
- Runtime 时间使用正确；
- Candidate Plan 已先形成；
- Reality Gaps 已按“孤立事实 / Research Topic”正确 routing；
- 没有为单条事实滥用 research_agent；
- 没有把一个完整 Topic 无意义切成多个微型 research_agent；
- 独立 Topics 可并行时没有无意义串行；
- 有依赖 Topics 没有错误并行；
- Main 与 ResearchFindings 的职责没有混淆；
- 天数、路线、交通时间和抵返时间合理；
- 开放 / 预约 / 天气等动态约束基于可靠证据或明确 unresolved；
- 图片只作 media，不作事实证据；
- 没有用猜测自证；
- 预算只汇总最终采用方案；
- 没有伪造当前精确事实；
- 最终结果是完整、一致、可执行的旅行计划。
