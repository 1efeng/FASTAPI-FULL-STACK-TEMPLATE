"""Agent execution boundary and runtime.

Product Runtime 通过 `AgentExecutor` port 调用 Agent；本包不反向依赖
Product 模块。Pydantic AI 实现（下一 milestone）落在 `agent.py` / `deps.py`。
"""
