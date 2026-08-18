# Trip Context Model v1

## 1. 目标

定义一次旅行规划需要的完整上下文。

旅行 Agent 不应该只处理地点和日期。

---

## 2. Context结构

```text
Trip Context

├ User Intent
│  ├ why travel
│  ├ relationship
│  └ experience goal
│
├ Travelers
│  ├ count
│  ├ age
│  └ ability
│
├ Constraints
│  ├ budget
│  ├ date
│  └ time
│
├ Preferences
│  ├ pace
│  ├ food
│  ├ culture
│  └ photography
│
├ Reality
│  ├ transportation
│  ├ opening rules
│  ├ reservation
│  ├ weather
│  └ cost
│
└ Risk
   ├ uncertainty
   ├ failure impact
   └ fallback
```

---

## 3. 决策原则

信息不是越多越好。

只有影响最终旅行决策的信息才值得获取。

判断标准：

如果不知道该信息，会不会改变路线、时间、预算或者体验？

如果不会，不需要搜索。
