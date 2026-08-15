# Cursor 施工指令 — Travel Agent v8 S2 Final

基于 `travel_agent_v8` commit `ab0738def24828b71c5c9ff60bf39bd2042414c2` 应用本 ZIP。

1. 从仓库根目录解压本包。
2. 执行 `python scripts/apply_travel_agent_s2.py`；若 baseline 校验失败，不要绕过，先报告 drift。
3. 执行 `uv lock`，确认 lock 中 Tavily 已移除、PydanticAI 2.28.0 / Harness 0.21.0 / DDGS 9.x 正确解析。
4. 运行 README 中 focused tests。
5. 运行全量 backend pytest + ruff + mypy/项目既有 lint。
6. 审查以下 invariant，不允许用“改 Prompt”替代 host 保证：
   - Main 8/6 与 Worker 8/18 独立；Product usage = Main + all Workers。
   - 每个 Main run 最多一次 `run_workflow`。
   - `verified` 只能来自该 Worker 本轮真实成功 Tool evidence。
   - image evidence 与 fact evidence 永久分离。
   - Worker failure 后不启动第二个 workflow。
7. 不实现前端图片展示；不要扩大本次 scope。
8. 测试全部通过后再提交。回报：diff 摘要、`uv lock` 变化、focused/full test 结果、任何未解决风险。
