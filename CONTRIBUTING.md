# 贡献指南

感谢你对全栈 FastAPI 模板感兴趣并愿意贡献!🙇

## 先讨论

对于**重大变更**(新功能、架构变更、大规模重构),请先发起一个 [GitHub Discussion](https://github.com/fastapi/full-stack-fastapi-template/discussions)。这样社区和维护者可以在你投入大量时间实现之前,对方案提供反馈。

对于小而直接的修改,你可以直接提交 Pull Request,无需先发起讨论。这包括:

- 拼写和语法修正
- 可复现的小 bug 修复
- 修复 lint 警告或类型错误
- 小的代码改进(例如移除无用代码)

注意,来自非团队成员 PR 不允许修改 `pyproject.toml` 或 `uv.lock`,以防止供应链风险。
如果你想添加新依赖,请创建一个新的 [Discussion](https://github.com/fastapi/full-stack-fastapi-template/discussions) 说明原因。

## 开发

关于配置开发环境、运行环境、代码检查、pre-commit 钩子等详细说明,请参阅[开发指南](development.md)。

## Pull Requests

提交 pull request 时:

1. 提交前确保所有测试通过。
2. 保持 PR 专注于单一改动。
3. 如果你改变了功能,请更新测试。
4. 在 PR 描述中引用相关的 issue。

## 自动化代码与 AI

我们鼓励你使用所有想用的工具来高效完成工作和贡献,这包括 AI(LLM)工具等。尽管如此,贡献应该包含有意义的人工介入、判断和上下文。

如果一个 PR 投入的**人工工作量**(例如编写 LLM 提示词)**少于**我们**审查它**所需付出的**工作量**,请**不要**提交这个 PR。

可以这样想:我们自己本来就能编写 LLM 提示词或运行自动化工具,那会比审查外部 PR 更快。

### 关闭自动化与 AI PR

如果我们看到似乎由 AI 生成或以类似方式自动化的 PR,我们会标记并关闭它们。

评论和描述也一样,请不要复制粘贴由 LLM 生成的内容。

### 人工精力拒绝服务

使用自动化工具和 AI 提交需要我们仔细审查处理的 PR 或评论,等同于对我们的**人工精力发起[拒绝服务攻击](https://en.wikipedia.org/wiki/Denial-of-service_attack)**。

提交 PR 的人花费的精力很少(一个 LLM 提示词),却在我们这边产生大量的工作(仔细审查代码)。

请不要这样做。

我们将不得不封禁那些用重复的自动化 PR 或评论骚扰我们的账号。

### 明智地使用工具

正如本叔(Ben Parker)所说:

> 能力越大,责任越大。

避免无意中造成伤害。

你手上有很棒的工具,请明智地使用它们,更有效地提供帮助。

## 有问题?

如果你对贡献有任何疑问,欢迎发起一个 [GitHub Discussion](https://github.com/fastapi/full-stack-fastapi-template/discussions)。
