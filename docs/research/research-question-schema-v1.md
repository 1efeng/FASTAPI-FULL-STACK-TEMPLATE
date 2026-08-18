# Research Question Schema v1

## 1. Research Agent定位

Research Agent 不是搜索助手。

它负责验证会改变旅行决策的不确定变量。

---

## 2. Research触发条件

必须满足：

- 信息动态变化
- 模型无法可靠知道
- 会影响最终方案

例如：

- 门票预约
- 开放时间
- 交通耗时
- 当前价格
- 天气风险

---

## 3. Research Question结构

```json
{
  "question": "八达岭是否适合第三天返程日",
  "reason": "影响路线安排",
  "decision_impact": "high",
  "priority": "P0"
}
```

---

## 4. 禁止模式

不要：

研究北京旅游

应该：

验证某个具体决策。

---

## 5. 输出要求

Research 返回：

- 事实
- 来源
- 置信度
- 对决策影响

不要返回大量原始搜索内容。
