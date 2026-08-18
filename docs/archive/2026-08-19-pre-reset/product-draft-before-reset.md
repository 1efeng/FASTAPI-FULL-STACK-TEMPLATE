# 行伴 Travel Agent 产品文档

> 文档状态：2026-08-19 产品语义重构基线  
> 产品方向：面向 C 端用户的通用旅行规划 Agent  
> 本文职责：定义 **用户为什么使用产品、什么叫一次好的旅行、产品需要做哪些决策、何时应该获取信息、何时必须停止获取信息、最终结果如何验收**。  
> 本文不定义 Agent / SubAgent / Tool / Framework / Gateway / Streaming 等技术实现；技术实现必须从本产品语义向下推导。

---

# 1. 产品一句话定义

> **行伴不是旅游信息搜索器，也不是 POI 日程生成器；它是在用户真实约束下，设计一组能够最大化其旅行目标与体验结果的可执行经历。**

旅行规划的目标不是“知道得最多”，而是：

```text
理解用户为什么旅行
↓
理解时间 / 预算 / 人群 / 已有安排等约束
↓
设计一组符合旅行目标的体验
↓
只获取让这些决策成立所需的最小现实上下文
↓
确认空间、时间、访问和资源上可执行
↓
在可行方案中选择最符合用户旅行目标的方案
↓
停止继续调查
↓
输出可执行计划
```

产品核心原则：

> **Don't fill knowledge gaps. Fill decision context.**  
> 不补齐所有未知，只补齐做旅行决策真正需要的上下文。

---

# 2. 第一性原理：用户购买的不是 POI，而是旅行结果

一个用户说“去北京三天”，表面上需要景点、酒店和交通，实际可能想获得完全不同的结果：

```text
情侣第一次旅行
→ 共同记忆、亲密陪伴、一起完成一些事情

带父母旅行
→ 陪伴、表达心意、舒适、让父母看到经典目的地

美食旅行
→ 吃到当地代表性食物、发现有趣餐馆和街区

经典打卡
→ 在有限时间完成最有代表性的地标

放松度假
→ 恢复精力、减少移动、获得安静和留白

文化旅行
→ 理解一个地方的历史、建筑、艺术和生活方式
```

因此：

```text
POI / 酒店 / 餐厅 / 交通
= 实现旅行结果的手段

Trip Outcome
= 产品真正需要优化的目标
```

产品不以“塞入更多景点”为默认成功标准。

---

# 3. Trip Intent：这趟旅行最终想得到什么

## 3.1 Trip Intent 是最高层产品语义

Trip Intent 回答：

> **用户为什么要进行这次旅行，旅行结束后希望获得什么？**

它高于普通 Preference。

```text
Trip Intent
→ 为什么旅行 / 最终想得到什么

Preference
→ 喜欢以什么方式旅行

Activity / POI
→ 具体安排什么
```

例如：

```text
Trip Intent:
和伴侣创造共同记忆

Preferences:
喜欢拍照、散步、不喜欢赶路

Activities:
景山日落、什刹海散步、一起登长城、安排一顿值得记住的晚餐
```

## 3.2 常见 Outcome 维度

内部可以识别以下语义维度，但产品不得强迫用户选择固定标签：

```text
relationship / 亲密陪伴
family_bonding / 家庭陪伴
care / 表达关心与照顾
landmark_completion / 经典打卡
food_experience / 美食体验
culture_learning / 文化理解
nature / 自然体验
relaxation / 放松恢复
achievement / 成就与挑战
novelty / 新鲜体验
photography_story / 摄影与分享
celebration / 纪念日与庆祝
exploration / 自由探索
```

一个旅行可以同时拥有多个 Outcome，并存在优先级。

## 3.3 Desired Experiences

产品不应该只保存抽象 Intent，还要把它落成希望出现的体验类型。

例如情侣北京旅行：

```text
Primary Outcomes
- 经典北京体验
- 情侣共同记忆

Desired Experiences
- 一个代表性文化地标
- 一个共同完成感较强的体验
- 一段适合散步 / 拍照的时间
- 一次有当地特色的饮食体验
- 每天留出不过度赶场的空间
```

之后才把 Experience 映射到故宫、长城、景山、什刹海、餐厅等具体对象。

---

# 4. Trip Contract：这趟旅行的现实边界

Trip Contract 定义不能被规划随意改变的输入条件。

至少包括：

```text
出发地 / 返回地
目的地或候选目的地
出发日期 / 返回日期 / 天数
人数
同行关系
总预算及预算口径
已经预订的交通 / 酒店 / 活动
必须参加的活动
不可改变的时间窗口
证件 / 签证 / 年龄等硬约束
```

可能还包括：

```text
老人 / 儿童
行动能力
饮食禁忌
慢性病或特殊身体限制
行李情况
自驾 / 公共交通偏好
是否接受早起 / 夜行
```

这些信息来自用户、当前会话和用户明确提供的已有安排，**不是通过外部搜索补出来的**。

---

# 5. People Context 与 Preference Context

## 5.1 People Context

同行者会直接改变什么叫“好计划”。

例如：

```text
年轻情侣
→ 可以接受更多步行，但需要体验感和共同记忆

带父母
→ 少换乘、少长距离步行、住宿舒适、午休和缓冲更重要

带儿童
→ 活动时长、用餐、休息、排队和卫生间可达性更重要
```

## 5.2 Preference Context

偏好包括：

```text
节奏：轻松 / 平衡 / 特种兵
兴趣：历史 / 美食 / 自然 / 购物 / 摄影 / 夜生活
住宿：位置 / 舒适度 / 品牌 / 房型
交通：地铁 / 打车 / 自驾 / 步行容忍度
饮食：预算 / 口味 / 禁忌 / 是否追求网红
体验：经典 / 小众 / 深度 / 随性
```

产品不机械追问完整偏好表。

只有当缺失偏好会明显改变候选方案时，才值得澄清；否则允许基于用户已有表达形成合理默认并继续规划。

---

# 6. Experience Strategy：先设计体验，再排 POI

完整规划不应从“目的地 Top 10 景点”开始。

正确的产品过程是：

```text
Trip Intent
+
Trip Contract
+
People / Preferences
↓
Experience Strategy
↓
Candidate Plan
```

Experience Strategy 回答：

```text
这趟旅行应该包含哪几种核心体验？
哪些体验是 must-have？
哪些只是 nice-to-have？
节奏应该怎样？
需要多少留白？
哪些体验可以共同满足多个 Outcome？
```

示例：北京三日情侣经典游。

不是：

```text
故宫 + 长城 + 天坛 + 颐和园 + 北海 + 南锣鼓巷 + 王府井……
```

而是先得到：

```text
一个北京代表性文化体验
一个共同完成感体验
一个情侣氛围 / 拍照体验
一个当地饮食体验
保持三天不过度赶场
```

再映射为具体地点和活动。

---

# 7. Candidate Plan：先提出可解释的候选方案

Candidate Plan 是在有限信息下形成的第一版旅行方案，不要求一开始就拥有所有现实细节。

它至少需要表达：

```text
每天的核心体验
大致区域 / 空间结构
住宿基地
主要跨城移动
关键时间锚点
预算大致结构
```

Candidate Plan 的作用不是直接成为最终答案，而是暴露：

> **为了判断这个计划是否成立、是否值得选，我们还真正缺哪些决策上下文。**

产品不应因为“某个事实不知道”就自动进行调查。

---

# 8. Minimum Sufficient Planning Context（MSPC）

## 8.1 定义

> **MSPC 是足以判断 Candidate Plan 是否可行，并能在主要候选方案之间选择最符合 Trip Intent 的方案的最小外部上下文集合。**

判断标准：

```text
少一个关键 Context
→ 可能导致方案不可执行或选错主要方案

多一个 Context
→ 不会改变可行性或主要取舍
```

后者不应该在当前规划阶段继续获取。

## 8.2 是否值得获取一个信息

Main 产品决策只需要问两个问题：

```text
1. 这个信息的不同可能值，会不会改变 Plan Feasibility？
2. 这个信息的不同可能值，会不会显著改变 Trip Outcome Quality？
```

如果两个答案都是 NO：

```text
→ 不获取
```

例如：

```text
景山门票是 ¥2 还是 ¥10
→ 对 5000 元双人三日游路线和 Outcome 都不产生实质变化
→ 不需要为了精确而继续调查
```

而：

```text
故宫目标日期是否开放
→ CLOSED 会直接让当天方案失效
→ 必须获取
```

---

# 9. Planning Context 的基础组成

旅行规划所需外部 Context 不按“景点 / 酒店 / 火车”这种业务对象分类，而按它解决的决策问题分类。

## 9.1 Space Context

回答：

> 地点之间如何组成一张真实可移动的空间网络？

需要的信息可能包括：

```text
地点位置
区域关系
住宿基地位置
主要地点间距离
移动方式
典型移动耗时
换乘复杂度
```

本质是一张 Travel Graph：

```text
Node
= 城市 / 车站 / 机场 / 住宿区域 / POI

Edge
= 距离 / 交通方式 / 行程时间 / 移动摩擦
```

产品不需要地点百科，只需要足以做路线决策的空间信息。

## 9.2 Time Context

回答：

> 活动和移动能否装进旅行时间窗口？

由以下信息共同决定：

```text
旅行总时间窗口
活动典型时长
移动时长
可进入时间窗口
已锁定活动时间
必要安全缓冲
```

“几点闭馆”本身不是目标；它只有在影响某个日程是否成立时才需要精确获取。

## 9.3 Access Context

回答：

> 用户在目标时间是否真的能完成这个体验？

可能包括：

```text
是否开放
是否预约
容量 / 限流
身份 / 年龄 / 证件条件
票务 / Permit / Visa 要求
交通是否运营
重要的临时限制
```

不是所有地点都需要查询所有 Access 字段，只获取会影响当前方案成立的部分。

## 9.4 Resource Context

回答：

> 当前方案消耗的资源是否在用户可接受范围内？

包括：

```text
Money
Time
Physical Energy
Attention / Planning Burden
Luggage / Mobility Friction
```

预算规划优先使用价格区间和预算 envelope，而不是追求所有小额费用的精确值。

例如：

```text
城际交通  ¥1200–1500
住宿      ¥600–1000
主要活动  ¥200–400
餐饮      ¥600–900
市内交通  ¥200–300
```

如果已经足以判断总预算 5000 可行，就不应该继续为了几十元差异调查。

## 9.5 Outcome-Relevant Context

回答：

> 哪些现实信息会明显影响 Trip Intent 的实现质量？

例如：

```text
情侣旅行
→ 日落 / 夜景时间、适合散步的区域可能有较高价值

带父母旅行
→ 步行距离、换乘复杂度、住宿位置可能有较高价值

美食旅行
→ 餐厅营业时段、区域餐饮密度和预约可达性可能有较高价值
```

同一个现实信息对不同 Trip Intent 的决策价值可能完全不同。

---

# 10. Freshness：不同信息需要不同的新鲜度

Freshness 不是单独一种旅行信息，而是每个 Planning Context Item 的属性。

例如：

```text
地点坐标
→ 长期稳定

常规开放规则
→ 中等新鲜度

某天临时闭馆
→ 高新鲜度

实时余票 / 实时房价
→ 极高新鲜度
```

产品不得把所有信息都按“越实时越好”处理。

因为过早查询执行级实时信息通常既昂贵，又不会提升当前规划质量。

---

# 11. Planning Context 与 Execution Context 必须分离

## 11.1 Planning Context

回答：

> **这个方案总体能不能成立、哪个方案更好？**

可以接受：

```text
合理区间
典型耗时
稳定规则
足够决策的近似成本
```

例如：

```text
郑州 → 北京高铁约 2–3.5 小时
单程二等座约一个合理价格区间
```

对于早期路线规划通常已经足够。

## 11.2 Execution Context

回答：

> **用户真正出发时具体怎么买、几点走、能不能进？**

包括：

```text
具体车次
实时余票
酒店实时房价
目标日期精确天气
临时关闭公告
当天运营状态
准确预约开放时间
```

只有当前决策阶段确实需要这些信息时才获取。

产品不得在用户只是做长期初步规划时，大量查询临近执行才有意义的数据。

---

# 12. Context Acquisition：按决策价值获取上下文

## 12.1 获取顺序

产品层不规定具体技术 Tool，但规定数据获取优先级：

```text
用户 / 已有会话中已经知道
→ 直接使用

合理估算即可完成当前决策
→ 使用 estimate / range

地点 / 位置 / 周边 / 路线等结构化现实信息
→ 优先结构化位置与路线数据源

天气等专门现实信息
→ 优先专门数据源

预约 / 政策 / 临时关闭 / 当前规则等动态事实
→ 使用当前公开权威信息

搜索摘要不足以支持 decision-critical 结论
→ 才升级读取关键来源正文

一个决策上下文本身 evidence-heavy、需要多来源比较且原始材料很多
→ 可以交由隔离研究能力压缩后返回决策结论
```

## 12.2 不允许“保险式调查”

如果更专门、更低成本的数据源已经足以支持当前 Context Requirement：

```text
→ 不为了“再保险一下”继续 Web 搜索
```

如果当前公开搜索摘要已经完整支持 decision-critical fact：

```text
→ 不为了“看看原文”默认继续抓取整页内容
```

## 12.3 Controlled Expansion

调查过程中发现新的信息，不自动产生新的调查分支。

只有当新信息：

```text
会使当前 Candidate Plan 不可行
或
会显著改变 Trip Outcome Quality / 核心取舍
```

才允许形成新的 Context Requirement。

否则记录为非关键提示或直接忽略。

---

# 13. 产品核心规划流程

完整规划产品流程固定为：

```text
User Request
      ↓
Understand Trip Intent
      ↓
Build Trip Contract
      ↓
People / Preference Context
      ↓
Experience Strategy
      ↓
Candidate Plan
      ↓
Identify Planning Decisions
      ↓
Derive Minimum Required Planning Context
      ↓
Context Acquisition
      ↓
Feasibility Evaluation
      ↓
Outcome Evaluation
      ↓
Revise only affected part of Plan
      ↓
Context sufficient?
   ├─ NO → only acquire newly required decision context
   └─ YES
      ↓
Budget / Route Finalization
      ↓
Final Plan
```

产品不要求固定步骤数量，也不要求固定调用次数；要求的是决策语义稳定和 Context Acquisition 有边界。

---

# 14. Feasibility Gate：先保证能执行

一个 Candidate Plan 在进入最终选择前，至少需要判断：

```text
Space Feasibility
地点与路线真实可达

Time Feasibility
移动和活动能装进时间窗口

Access Feasibility
目标体验在目标时间可以进入 / 使用

Resource Feasibility
预算、体力和其他资源不明显超出约束

Contract Satisfaction
没有违反用户不可改变的硬约束
```

关键项无法可靠确认时，产品必须：

```text
明确 unresolved / uncertainty
并采用保守方案、备选方案或提示用户临近执行时确认
```

不能用“看起来合理”的旧知识补全。

---

# 15. Outcome Evaluation：可行之后再判断是不是好旅行

可行不等于好。

在多个 feasible plans 中，产品需要比较：

```text
Trip Intent Alignment
是否实现用户最重要的旅行目的

Experience Quality
核心体验是否有代表性、记忆点和组合价值

Pace
是否符合同行人与节奏偏好

Friction
是否存在不必要的通勤、排队、折返和搬行李

Diversity
体验是否有合理变化，而不是连续重复同类活动

White Space
是否根据用户风格留下合理缓冲和自由时间
```

例如情侣旅行中，多塞一个普通 POI 不一定比保留一段日落、散步或有质量的晚餐更好。

---

# 16. Stop Rule：什么时候必须停止继续调查

产品最重要的能力之一是知道什么时候已经“够了”。

当以下条件成立：

```text
1. 核心 Trip Contract 已明确
2. Candidate Plan 的主要空间 / 时间 / Access / Resource feasibility 已足够判断
3. 已经能够在主要候选方案之间根据 Trip Intent 做选择
4. 剩余未知不会实质改变路线、预算成立性或核心 Outcome
```

则：

> **STOP acquiring context and finish the plan.**

产品不追求百科全书式完整。

以下行为属于过度调查：

```text
为了几十元的小额差异重复搜索
为了一个 optional 活动提前确认全部规则
搜索摘要已经足够却继续打开多个正文来源
专门位置 / 路线数据已经足够却继续 Web 复核
发现与计划无关的新事实后顺手继续调查
计划已成立后继续为了“更完整”增加来源
```

---

# 17. 用户澄清原则

产品不使用长问卷。

只有缺失信息会显著改变：

```text
Trip Intent
Trip Contract
核心路线
同行者安全 / 行动约束
主要预算边界
不可逆的方案级取舍
```

才需要主动澄清。

否则：

```text
根据用户当前表达形成合理默认
并在最终计划中透明体现关键假设
```

产品不得重复询问已经知道的信息。

---

# 18. 修改计划的产品行为

用户说：

```text
“第二天轻松一点。”
“预算降到 4000。”
“这次主要想陪爸妈，不想太赶。”
“我更想吃，不想逛那么多景点。”
```

产品应该：

```text
理解 Trip Intent / Contract / Preference 哪一层发生变化
↓
识别受影响的 Experience Strategy / Candidate Plan 部分
↓
只重新获取受影响的 Planning Context
↓
重新评估 feasibility + outcome
↓
输出完整修订版
```

不从零重新研究整座城市。

## 18.1 跨会话继续

用户应能够：

```text
今天生成计划
↓
关闭产品
↓
之后回来
↓
继续修改同一趟旅行
```

产品需要记住已经明确的 Trip Intent、Trip Contract、用户确认的关键取舍和最近一版完整计划；不得要求用户反复重新描述已经确认的信息。

产品不承诺把全部历史原文永久作为规划上下文。历史信息是否继续参与规划，以是否仍然影响当前旅行决策为准。

## 18.2 外部信息失败时的产品行为

部分现实信息暂时无法获得时，不应默认让整份旅行计划失败。

产品根据该 Context 的决策重要性处理：

```text
非关键 Context 失败
→ 使用合理降级 / 区间 / 暂不承诺精确值
→ 计划继续

关键 Context 无法确认
→ 明确 uncertainty / unresolved
→ 使用保守方案或备选方案
→ 不伪造当前事实
```

用户看到的是“哪一部分暂时无法确认，以及它是否影响方案”，而不是底层 Provider / Tool / Framework 错误。

---

# 19. 单点旅行问题与完整规划分离

用户问：

```text
“东京明天天气怎么样？”
“京都到大阪多久？”
“故宫明天开吗？”
```

就回答当前问题。

只有当用户的目标明显是形成或修改完整旅行方案时，才进入完整 Trip Intent → Planning Context 流程。

---

# 20. 完整旅行计划输出 Contract

最终输出不追求固定 UI，但语义上至少需要包含：

```text
## 这趟旅行怎么设计
简要说明 Trip Intent、节奏与总体策略

## 行程概览
日期 / 城市 / 住宿基地 / 核心体验

## Day N
核心体验、区域顺序、主要移动、合理缓冲

## 行前必须处理
真正影响执行的预约 / 证件 / 购票 / 当前规则

## 住宿建议
优先给区域和选择逻辑；用户要求时再给具体候选

## 美食 / 体验建议
服务 Trip Intent，而不是机械补一个“美食章节”

## 预算
使用足以判断总预算的区间和明确已知费用

## 不确定性 / 临近出发再确认
只列真正 execution-time 才值得确认的事项
```

第一阶段 Markdown 可以作为展示语义载体，但产品语义不依赖具体渲染技术。

---

# 21. 产品信任原则

## 21.1 不是所有事实都要求同样精度

根据 Decision Value 区分：

```text
Estimate
合理估算即可完成决策

Range
需要控制预算 / 时间 envelope，但不要求单点精确

Verified Current Fact
错误会导致计划明显失效或误导用户

Execution-time Fact
只有临近出发才值得精确获取
```

## 21.2 关键动态事实不能伪造

例如：

```text
签证 / 入境
当天开放 / 临时关闭
必要预约
重要交通运营规则
会显著影响预算或路线的当前价格规则
```

当这些信息无法可靠获得时，必须明确不确定性。

## 21.3 来源数量不是质量指标

产品不追求“来源越多越可信”。

更好的目标是：

```text
最少但足够的高质量证据
支持真正 decision-critical 的结论
```

---

# 22. 什么叫一次好的旅行计划

产品质量至少从六个维度评估。

## 22.1 Feasibility

用户按照计划是否真实有机会完成旅行。

## 22.2 Intent Alignment

计划是否服务用户真正想从旅行中获得的结果。

## 22.3 Constraint Satisfaction

日期、预算、人数、已有预订、特殊人群限制是否满足。

## 22.4 Experience Quality

计划是否有节奏、有记忆点、不过度折返、不只是机械堆 POI。

## 22.5 Evidence Sufficiency

真正影响执行的动态事实是否拥有足够依据；不重要的信息没有过度核验。

## 22.6 Information Economy

产品是否只获取对决策真正有价值的上下文，并在足够时及时停止。

---

# 23. 代表性产品 Case

这些 Case 用于验证产品语义，而不仅是最终文案。

## Case A：情侣第一次北京

输入：

```text
郑州出发
北京 3 天
2 人情侣
5000 元
第一次去北京
```

预期：

```text
经典地标 + 共同记忆
不会为了覆盖更多 POI 牺牲全部留白
至少存在适合两个人共同体验 / 散步 / 拍照的安排
关键预约和路线真实可执行
预算稳在边界内
```

## Case B：带父母北京

同样 3 天和预算，但 Trip Intent 变成陪父母。

预期：

```text
减少长距离步行和频繁换乘
住宿基地更重视位置和舒适
长城等高体力体验提供更舒适方案
日程留更多休息时间
经典体验仍保留
```

不能只是把情侣版 POI 原样复制。

## Case C：北京美食优先

预期：

```text
餐饮区域和营业时间进入 Outcome-Relevant Context
景点数量主动下降
住宿 / 日程围绕吃饭区域和时间优化
```

## Case D：特种兵经典打卡

预期：

```text
用户明确接受高强度
POI coverage 权重上升
但仍必须满足真实时间 / Access / 交通 feasibility
```

## Case E：长期规划 vs 临近执行

同一目的地：

```text
三个月后旅行
→ 主要获取 Planning Context

明天出发
→ Execution Context 权重明显增加
```

产品不能对两种请求执行同样的实时调查深度。

---

# 24. 核心产品指标

## 用户价值

```text
完整规划完成率
用户接受 / 继续修改率
历史计划继续率
计划被用户实际采用的信号
```

## 质量

```text
Feasibility failure rate
Trip Intent alignment eval
Constraint violation rate
Budget consistency error
关键动态事实错误率
```

## Context Efficiency

必须新增并长期关注：

```text
每个完整规划获取的 Planning Context 数量
非 decision-critical 调查比例
重复调查率
Web / 重型内容获取占比
Context sufficient 后继续调查率
Planning Context 与 Execution Context 混用率
```

## 体验与性能

```text
端到端完成耗时
用户等待中的可理解进度
完整规划平均模型 / 外部数据成本
失败与降级率
```

具体目标阈值必须通过真实 Eval / 灰度数据确定，不在没有数据时拍脑袋承诺。

---

# 25. 产品非目标

当前明确不做：

```text
❌ 旅游百科全书
❌ 为了展示“联网能力”而查询所有事实
❌ 所有价格都追求实时精确
❌ 所有景点都查完整开放 / 票价 / 预约字段
❌ 默认把目的地 Top N POI 塞满每天
❌ 为用户建立复杂旅行问卷
❌ 在长期规划阶段提前查大量实时余票 / 房价 / 天气
❌ 来源越多越好的 Research 产品
❌ 为了技术上的多 Agent 而改变产品决策流程
```

支付、订单、退款等交易能力若未来引入，需要独立产品定义。

---

# 26. 产品决策原则

1. **Outcome first。** 先理解用户想从旅行中得到什么，再谈去哪。  
2. **Plan before research。** 先形成 Experience Strategy / Candidate Plan，再判断需要什么现实上下文。  
3. **Decision context, not knowledge completeness。** 不补知识缺口，只补决策上下文。  
4. **Minimum sufficient context。** 获取足以做正确主要决策的最小上下文。  
5. **Specialized reality before generic Web。** 专门结构化现实数据能解决时，不做保险式 Web 调查。  
6. **Planning ≠ Execution。** 不在错误的时间查询错误精度的信息。  
7. **Feasibility before optimization。** 先确保能执行，再比较哪个方案更好。  
8. **Intent decides trade-offs。** 同一个目的地对情侣、父母、美食用户应该产生不同计划。  
9. **Uncertainty is allowed; fabrication is not。** 不重要的信息可以估算，重要但无法确认的信息必须明确不确定。  
10. **Stop is a product capability。** 信息已经足以支持决策时，继续调查本身就是产品缺陷。  
11. **Model freedom belongs in decisions, not endless discovery。** 模型应该自由理解用户、设计体验和做取舍，而不是无限制搜索互联网。  
12. **Product success depends on trip outcomes, not Agent count, source count, or Tool count。**

---

# 27. 本文与技术文档的边界

本文是产品行为意图基线。

后续技术架构需要回答：

```text
Trip Intent 如何表达和更新？
Experience Strategy / Candidate Plan 是否需要内部结构化状态？
Planning Context Requirement 如何建模？
Context Acquisition 如何选择结构化数据 / Web / 隔离研究？
如何保证 Context sufficient 后停止继续调查？
如何避免原始外部内容污染长期模型上下文？
如何观测 Intent alignment / Context efficiency？
```

但以下概念不应反向污染产品语义：

```text
Agent / SubAgent
具体 Framework
Tool schema
LiteLLM
Prompt caching
Context compaction 实现
SSE protocol
数据库 / Redis
```

技术方案可以替换，产品目标不应随框架变化。

---

# 28. 当前产品定义状态

> **行伴下一阶段的核心不是“让 Agent 查到更多旅行信息”，而是建立 Outcome-driven、Minimum-Sufficient-Context 的旅行规划能力：理解用户真正想获得的旅行结果，形成 Experience Strategy 与 Candidate Plan，只获取会改变 feasibility 或 Trip Outcome 的现实上下文，在信息足够时及时停止，并输出一份真实可执行、符合用户旅行目的的完整计划。**
