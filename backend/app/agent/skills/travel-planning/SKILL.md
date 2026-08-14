---
name: travel-planning
description: 创建、重新规划或修改完整旅行行程的专业旅行规划技能。适用于多日旅行规划、每日路线安排、行程调整、旅行节奏、交通与预算设计，以及已有完整行程的修改。仅当用户明确要求规划、安排、重新规划或修改完整旅行时使用；不要用于问候、闲聊、普通旅行问答、单个景点介绍、轻量推荐、单次天气、交通或开放时间查询。
---

# 旅行规划

生成真实可执行、路线合理、符合用户偏好的完整旅行计划。

Main Agent 始终负责最终判断、最终规划和最终回答。
本 Skill 提供规划方法和输出规范，不定义固定 Workflow。

## 1. 理解旅行需求

关注真正影响行程的信息：

- 目的地与城市路线
- 日期或旅行天数
- 出发地与抵达 / 返程时间
- 旅行者组成及行动能力
- 预算
- 旅行风格与兴趣
- 交通偏好
- 必去 / 避开项目
- 住宿区域要求
- 其他明确约束

不要把旅行规划变成问卷。

在开始 Travel Researcher Research 前，先确认是否缺少会直接改变整体方案的关键条件。
例如进出城市、实际旅行日期 / 时间范围、是否跨城等核心信息如果当前请求存在歧义，应先简洁追问。

关键条件未明确时，不要先读取本 Skill、不要委派 Research，也不要猜测核心路线。

对不会明显改变整体方案的非关键偏好，可以采用合理假设。
会显著影响预算的核心交通方案（如是否购买 JR Pass 等 Pass / 周游券）不要预先假设，应等 Research 比价后由 Main 决定。

## 2. Travel Researcher

完整旅行规划天然需要多主题 Research。

只要进入以下任一模式：

- 创建完整旅行计划
- 重新规划完整旅行
- 修改已有完整旅行计划

Main 必须调用：

`delegate_task(agent_name="travel-researcher", task="...")`

由 Travel Researcher 在独立 Context 中完成所有与最终计划有关的外部 Research。

固定链路：

`Main → 必要需求澄清 → travel-planning Skill → Travel Researcher → Research Findings → Main 选定最终方案 → Budget / FX（按需）→ Markdown Contract → Main Final Synthesis`

规划模式下：

- Main 不直接调用 `search_travel_info`
- Main 不直接调用 `search_maps`
- Main 不直接调用 `get_weather`
- Research 中间 Tool Result 留在 Travel Researcher Context
- Main 只接收 Research Findings
- 如果 Findings 有影响最终计划的关键缺口，继续委派 Travel Researcher 补充

Travel Researcher 只负责 Research，不生成最终完整旅行计划。

### Research Brief

Main 的委派描述必须自包含，至少包括：

1. Runtime 当前日期、星期、时区、年份
2. 旅行背景
3. 用户约束
4. Research 目标
5. Research 范围
6. 当前信息的新鲜度要求
7. Anti-confirmation 要求
8. Research Findings 返回要求
9. “只做 Research、不生成最终计划”的职责边界
10. 币种要求：Research 以当地货币核实事实价格，Findings 中每个价格标注币种

普通旅行问答不是完整旅行规划，可由 Main 按需直接调用 Tool。

## 3. Research 新鲜度

当前旅行事实必须以 Runtime 当前时间为基准。

对于：

- 门票 / Pass 价格
- 预约规则
- 开放 / 闭馆时间
- 当前运营状态
- 交通政策
- 节假日特殊安排
- 其他易变化事实

Research 必须：

- 优先 latest / current / official / 最新 / 当前 / 官方
- 用户未询问历史时，不主动使用旧年份
- 需要年份时使用 Runtime 当前年份
- 旧资料不能直接当作当前事实
- 无法确认时明确标记不确定性
- 不把未经确认的模型猜测写进下一轮 Query 当作前提

天气只在与实际旅行日期相关时 Research。
没有实际旅行日期时，不应把“今天的天气”当作未来旅行计划依据。

## 4. 设计可执行路线

优先：

- 同区域活动集中安排
- 减少跨区域往返
- 避免明显回头路
- 控制每天长距离移动
- 给交通、排队、吃饭和休息留出真实时间
- 根据旅行者情况调整强度
- 保留必要缓冲

亲子、老人或轻松旅行应降低强度并增加缓冲。
高强度旅行可以提高活动密度，但仍必须保证实际可执行。

相关情况下根据 Research Findings 检查：

- 开放 / 关闭时间
- 最晚入场时间
- 固定闭馆日
- 预约时间
- 天气
- 抵达 / 返程时间
- 飞机 / 高铁时间
- 城际交通
- 排队时间

不得生成明显存在时间冲突的行程。

## 5. 让预算参与规划

根据预算调整：

- 住宿
- 城际交通
- 当地交通
- 景点与付费体验
- 餐饮
- 其他消费

没有可靠价格时使用区间。
不要编造未经验证的精确金额。
若方案可能明显超预算，应主动调整或指出主要超支来源。
最终路线 / 交通 / 住宿方案确定后，涉及多项费用时使用 `calculate_budget` 做确定性汇总。
计算器只接收最终采用方案的项目，不得把备选方案价格混入最终预算。

所有金额必须明确币种，不得仅用 "¥" 表示（对中文用户易误读为人民币）。
当地货币是事实价格；人民币等换算金额只能由 Main 通过 `convert_currency` 基于当前参考汇率换算，不得与事实价混写。
币种表达规则见 Markdown Contract「币种规范」。

## 6. 创建完整旅行计划

当用户明确要求生成完整旅行计划时：

1. Main 理解需求。
2. 如果缺少会改变整体方案的关键条件，先向用户做简洁澄清；关键条件明确前不要开始 Research。
3. 对不影响整体方案的非关键偏好采用合理假设。
4. 读取本 Skill。
5. 必须委派 Travel Researcher。
6. 等待 Research Findings 返回。
7. Main 根据 conversation、用户约束和 Findings 选定最终路线、交通、住宿与每日节奏。
8. 涉及多项费用时调用 `calculate_budget` 汇总最终采用方案；需要人民币等辅助参考时调用 `convert_currency`。
9. 计算完成后读取 `references/markdown-contract.md`。
10. 严格按照 Markdown Contract 输出。
11. 返回完整旅行计划，而不是 Research 摘要或景点清单。

普通旅行问答不要读取 Markdown Contract。

## 7. 修改已有旅行计划

当用户要求修改已有完整计划时：

1. 将 conversation 中最近一次完整旅行计划视为当前版本。
2. 理解用户真正想改变的内容。
3. 保留未被修改的约束、偏好和有效安排。
4. 必须委派 Travel Researcher Research 受影响的信息。
5. Main 根据 Findings 检查时间、路线、交通和预算连锁影响。
6. 必要时重新平衡其他日期，并重新调用 `calculate_budget` / `convert_currency` 更新受影响预算。
7. 计算完成后读取 `references/markdown-contract.md`。
8. 返回新的完整 Markdown 旅行计划。

不得只返回 Patch、Diff、修改项列表或单独修改后的某一天。

普通解释性问题不是修改，直接回答即可。

## 8. 最终质量检查

输出完整计划前确认：

- 最新用户要求已体现
- Runtime 时间已正确用于相对日期和当前信息判断
- Research Findings 已返回
- 天数和 Day 数量一致
- 路线顺序合理
- 没有明显折返
- 主要交通时间现实
- 抵达 / 返程时间合理
- 开放、预约、天气等约束已考虑
- 当前事实没有被旧年份资料错误替代
- 没有把未经核验的猜测通过搜索“自证”
- 预算没有明显违背用户要求
- 最终预算只汇总实际采用方案，没有混入未采用备选价格
- 预算模块金额币种明确，未被裸 "¥" 误读为人民币
- 没有伪造未经验证的精确事实
- 用户明确要求没有遗漏
- 修改时保留了未涉及内容
- 最终结果是一份完整旅行计划

不要创建额外 Validator Agent 或 Validator Workflow。

## 核心原则

- 模糊、概率性的旅行判断交给 Main。
- 当前日期和星期由 Runtime 动态提供。
- 外部旅行事实由 Travel Researcher Research。
- Research 中间上下文与 Main 最终规划上下文隔离。
- Travel Researcher 只返回 Findings。
- Main 是唯一最终旅行计划语义负责人。
- 完整计划必须遵守 Markdown Contract。
- 不得为了内容丰富而编造事实。
- 优先保证旅行真实可执行，而不是增加景点数量。
