# Travel Agent Routing Architecture v1

## 1. 总体流程

```text
User
 |
Intent Understanding
 |
Candidate Planner
 |
Decision Gap Analyzer
 |
Research Router
 |
Reality Layer
 |
Evidence
 |
Final Planner
 |
Travel Plan
```

---

## 2. Candidate Planner

负责生成初始方案。

不要求所有事实已经验证。

目标：发现可能方案。

---

## 3. Decision Gap Analyzer

分析：

哪些未知信息会改变方案。

输出研究需求。

---

## 4. Reality Layer

数据获取优先级：

1. 结构化API

- POI
- Maps
- Weather
- Railway

2. 官方信息

- 门票
- 预约
- 开放规则

3. Web Search

用于补充非结构化信息。

---

## 5. Research Agent

采用bounded模式：

- 明确问题
- 限制范围
- 返回压缩证据

禁止自由探索式搜索。

---

## 6. 性能原则

避免：

User -> Search -> Search -> Search -> Plan

因为会导致：

- token膨胀
- context污染
- 决策质量提升有限

正确：

先决策，再验证。
