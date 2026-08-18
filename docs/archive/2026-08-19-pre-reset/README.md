# 2026-08-19 Pre-reset 文档归档

> 状态：ARCHIVED / NON-SOT  
> 归档时间：2026-08-19  
> 目的：在 Travel Agent 产品与架构重新从 0 定义前，冻结此前文档历史。  
> 规则：本目录及其引用的历史内容只用于追溯，不得作为当前产品、架构、施工或代码实现依据。

## 1. 不可变恢复点

归档基准 Git HEAD：

```text
31c4cbd34b6d657ba040f2b17a46a78f7f3a16ec
```

**该提交中的整个 `docs/**` 文档树都视为 reset 前历史快照。**

也就是说，任何 reset 前已经存在的产品、架构、接口、数据库、部署、安全、可观测性、开发、前端、ADR、Research、路线图等文档，都可以通过该提交恢复，但都不自动拥有 reset 后的决策权。

下面额外列出最容易被误当成 SOT 的旧主线文档 Git blob：

| 原路径 | Git blob | 状态 |
|---|---|---|
| `docs/产品文档.md`（reset 前已提交版本） | `552f2200df8fcffc40399367abf721f0f5414810` | ARCHIVED |
| `docs/架构v8.md` | `dfae7bcb8adb3288d35e12e8fd6663ce621bd089` | ARCHIVED |
| `docs/sub_search_agent架构设计文档.md` | `f57e096a4d565f5905e6bd47c906b1b32345e939` | ARCHIVED |
| `docs/Research Checklist 施工方案.md` | `703013bccc67c4c4ccc28ce302c56f50e240582d` | ARCHIVED |
| `docs/施工路线图.md` | `53212cfff3de1bf26228d6be9e6f5400a980f098` | ARCHIVED |
| `docs/文档体系.md` | `6f549267c8c8154061b8da60991f97ca0688efc1` | ARCHIVED |
| `docs/v6认知核心溯源.md` | `abe9851aef6148aae6defa3ea8b488e4933f299d` | ARCHIVED |

恢复示例：

```bash
git show dfae7bcb8adb3288d35e12e8fd6663ce621bd089
```

或按归档基准提交读取原路径：

```bash
git show 31c4cbd34b6d657ba040f2b17a46a78f7f3a16ec:docs/架构v8.md
```

## 2. 2026-08-19 未提交产品稿

`docs/产品文档.md` 在 reset 前存在一份尚未提交的 Outcome-driven / MSPC 产品重构稿。该稿不是旧 HEAD 的内容，因此单独保存为：

```text
product-draft-before-reset.md
```

它同样是历史参考，不自动继承为新的 Product SOT。

## 3. ADR 处理

`docs/adr/` 中 2026-08-19 reset 之前的 ADR 全部视为 **Historical ADR**。

它们可以解释过去为什么做过某个决策，但 reset 之后：

```text
旧 ADR ≠ 当前 Architecture Decision
```

任何仍值得保留的决定，都必须由新的产品定义和新架构重新推导、重新采纳；不能因为“以前 ADR 写过”就自动继承。

## 4. Reset 原则

从本归档点之后：

```text
旧产品定义       → 不继承
旧架构版本       → 不继承
旧 Research 方案 → 不继承
旧施工路线图     → 不继承
旧 ADR 决策      → 不自动继承
```

但：

```text
真实代码 CURRENT
真实测试结果
真实 benchmark / incident evidence
用户已经确认的产品事实
```

仍然可以作为新设计的客观输入。

新设计必须从：

```text
用户价值
→ 产品定义
→ 系统能力需求
→ 架构边界
→ 专项契约
→ 施工路线
```

重新向下推导。
