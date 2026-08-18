# Travel Agent 产品与架构重构决策文档 v1

## 1. 背景

当前 Travel Agent 已完成多轮架构探索。

核心实验结论：

- 通用大模型已经具备较强的旅行规划能力。
- 单纯增加搜索不会显著提升规划质量。
- 自由搜索会造成 token 浪费、上下文膨胀和决策不稳定。

因此产品方向从“搜索增强型 Agent”调整为“旅行决策 Agent”。

---

## 2. 产品核心判断

用户购买的不是景点列表，而是一份符合个人目标的旅行体验。

需要理解：

- 为什么旅行
- 和谁旅行
- 想获得什么体验
- 可接受节奏
- 不接受什么

例如：

情侣旅行：
- 创造共同记忆
- 陪伴感
- 拍照
- 浪漫体验

父母旅行：
- 舒适
- 安全
- 少走路

---

## 3. DeepSeek Baseline 实验结论

### B0: DeepSeek V4 Flash 无联网

结果：

- 18.8 秒
- 输入 211 tokens
- 输出 1854 tokens

结论：

裸模型已经可以完成：

- 用户需求理解
- 路线规划
- 预算估算
- 节奏安排

不足：

- 动态事实不可靠
- 不知道哪些信息必须验证
- 缺少旅行价值排序

---

### B1: DeepSeek V4 Flash + Web Search

结果：

- 29.5 秒
- 搜索 6 次
- 47+ 来源
- 输入 43930 tokens

结论：

联网增加事实能力，但没有明显提升规划质量。

问题：

- 搜索成本高
- 大量信息没有改变决策
- 模型不知道应该搜索什么

---

## 4. 新架构原则

错误方向：

用户输入 -> 搜索 -> 生成计划

正确方向：

用户输入
↓
理解旅行目标
↓
候选方案
↓
发现决策缺口
↓
精准验证
↓
Final Plan

---

## 5. Research Agent 新定位

Research Agent 不是搜索助手。

它负责验证会改变旅行决策的不确定变量。

错误：

“研究北京旅游”

正确：

“验证八达岭是否适合第三天返程日，包括交通、开放、风险。”

---

## 6. Research Router

未来增加 Research Router。

输入：Candidate Plan

输出：需要验证的问题。

每个问题包含：

- question
- why_needed
- decision_impact
- priority

---

## 7. Context Acquisition 原则

现实信息获取优先级：

1. 结构化 API
   - POI
   - Maps
   - Weather
   - Railway

2. 官方信息
   - 预约
   - 门票
   - 开放时间

3. Web Search
   - 非结构化补充

原则：结构化数据优先，搜索兜底。

---

## 8. 目标架构

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

---

## 9. 下一步

P0：完成产品文档

P1：定义 Trip Context Schema

P2：定义 Research Question Schema

P3：重新设计 Agent Routing

暂缓：

- 增加更多 Agent
- 增加更多搜索能力
- 无限优化 Search Prompt

---

## 10. 产品定位

不是打造一个会搜索的旅行 Agent。

而是打造一个理解用户旅行目的，并知道哪些现实信息值得验证的旅行决策系统。
