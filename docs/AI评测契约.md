# AI 评测契约

> P0 目标：建立 Release Gate，不自研 Eval Platform。  
> 平台：eval 平台选型 M10 再决策；决策前以 deterministic 评估 + 轻量语义评估为主。

# 1. Release Rule

以下变化必须跑 AI baseline：

- system prompt；
- Skill；
- Main / Researcher policy；
- model；
- logical model routing；
- Tool schema；
- LiteLLM fallback policy；
- Context behavior；
- Critical Research policy。

# 2. Deterministic vs AI Eval

```text
pytest
→ exact deterministic contract

AI eval（平台 M10 再决策，当前轻量语义评估）
→ semantic quality / trajectory
```

不要用 LLM judge 替代本可以 exact assert 的数学 / schema / error tests。

# 3. P0 Dataset

至少包含：

## E001 Chat

普通问候不误触发完整 planning。

## E002 Current Fact

动态事实会调用合适 Tool / Research，不伪造。

## E003 Clarification

只问真正改变方案的关键条件。

## E004 Full Planning

完整 Day count、结构和整体可执行性。

## E005 Research Delegation

完整规划按当前职责委派 Researcher。

## E006 Budget

数学一致。

## E007 Currency

当地货币 / 换算规则正确。

## E008 Plan Modification

继承旧约束，只重新处理受影响内容。

## E009 Tool Degradation

Weather/Maps/FX/Search 失败行为符合 Contract。

## E010 LiteLLM Fallback

Primary failure 时能走兼容 fallback；全部失败映射统一模型错误。

## E011 Runtime Guard

recursion / model-call / tool-call limit 能停止 runaway。

## E012 Critical Fact Trust

关键当前事实包含来源和 freshness，无法核实时不伪造。

## E013 External Prompt Injection

网页文本不能改写 system rules 或请求 Secret。

# 4. Evaluator Types

优先组合：

- code/deterministic evaluator；
- structure evaluator；
- trajectory evaluator；
- LLM-as-judge（只用于难以 deterministic 的质量项）；
- human review for sampled high-risk cases。

# 5. Experiment

每次重要 Prompt / Model change 创建可比较 experiment，保留：

- git commit；
- model；
- prompt/skill version；
- dataset version；
- gateway policy version（相关时）。

# 6. Threshold

阈值必须来源于基线数据，不凭空宣称“95% 就够”。

灰度前至少要求关键阻断 case 不能退化。

# 7. Production Feedback

P1 把真实失败 trace 经过脱敏后回流 Dataset。

# 8. 成本

Eval 自身也要有成本预算，批量 judge 不应无界调用高价模型。
