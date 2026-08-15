# Travel Agent v8 — S2 Final Deep Research Closure

> 基线：`travel_agent_v8` @ `ab0738def24828b71c5c9ff60bf39bd2042414c2`  
> 上一版：`travel_agent_v8_S1_total_web_and_deep_research.zip`  
> 上一版 SHA256：`a380d3e0e441ae1f1a03263c8a2e6b309c891f27543e2c8d826710a5f95094a0`

## S2 目标

S2 不重写 Harness `DynamicWorkflow`。它只补齐 S1 审查发现的 5 个闭环：

1. **限制隔离，计费/观测聚合**
   - Main 继续使用 `8 model requests / 6 tool calls` 独立预算。
   - 每个 Research Worker 继续使用 `8 / 18` 独立预算。
   - Harness 继续 `forward_usage=False`，避免 Worker 消耗 Main role budget。
   - 新增 request-scoped `ResearchRequestState`，通过 PydanticAI hooks 捕获 Worker 的真实 ModelResponse / requests / tool_calls，并在 Product `_to_agent_usage` 中与 Main 显式合并。
   - 未能关联到 ModelResponse 的 request 保留为 `unattributed_model_requests`，不会伪装成 0 token。

2. **每个 Main run 最多一次 Deep Research workflow**
   - 新增 `SingleWorkflowCallGate`。
   - 第一次 `run_workflow` 正常执行；第二次由 host 用 `SkipToolExecution` 拒绝，返回 `DEEP_RESEARCH_ALREADY_USED`，不会再次进入 Harness/Worker。
   - gate 使用 `for_run()` 生成独立状态，不会跨请求串状态。

3. **Verified 必须绑定实际 Tool evidence**
   - 新增 per-Worker `WorkerEvidenceTrace`。
   - `web_search/web_fetch`：只有本 Worker 本轮真实成功结果中的 URL 才能支撑 Web `verified`。
   - `get_weather/search_maps`：只有真实成功执行才可作为 `tool_evidence`。
   - 失败字符串（包括中文“失败/未能/无法/缺少”等）不会被误判为成功证据。
   - 模型伪造 URL / 伪填 Tool 名时，Host 将 `verified` 降级为 `unresolved`。
   - `image_search` 使用独立 media registry，永远不进入 fact evidence registry。

4. **真实图片 trajectory**
   - POI Worker → `image_search` → DDGS normalized row → `ResearchFindings.media` → `run_workflow` result → Main。
   - Host 以 `(image_url, source_page_url)` 对实际 Tool result 做 attestation，并用真实 Tool metadata 覆盖模型自填的 title/width/height/source。
   - weather-only Worker deterministic test 明确要求 `image_search == 0`。

5. **H1 行为回归迁移**
   - `test_research_routing.py` 已恢复为完整 trajectory suite（500+ 行）。
   - 覆盖 casual / inspiration / stable plan / single-axis Quick Research / explicit single verification / multi-axis workflow / partial failure / modification routing / search dedupe / second workflow rejection / per-run gate reset / media to Main。
   - 旧 `test_optional_researcher_routing.py` 在 apply 脚本中删除；行为覆盖迁移后不再保留旧 Optional Researcher API。

## 应用方式

**必须从仓库根目录执行，且 HEAD 必须仍是上面的基线 commit。** S2 包已经包含 S1 total 的全部 overlay，因此不要求先单独解压 S1。

```bash
# 1) 确认基线
git checkout travel_agent_v8
git rev-parse HEAD
# 预期：ab0738def24828b71c5c9ff60bf39bd2042414c2

# 2) 在仓库根目录解压本 ZIP（覆盖同名文件）
unzip -o travel_agent_v8_S2_final_deep_research_closed.zip

# 3) 应用 S2 对基线外文件的 fail-closed patch / deletion
python scripts/apply_travel_agent_s2.py

# 4) S1 已改依赖，重建 workspace lock
uv lock

# 5) 安装后端依赖
cd backend
uv sync
```

`apply_travel_agent_s2.py` 会：

- 校验 HEAD；
- 校验基线 `pydantic_executor.py` Git blob SHA；
- 校验 S2 overlay 与依赖 pin；
- patch `pydantic_executor.py` 的 non-stream + stream usage collector；
- 删除已经迁移完成的旧 Optional Researcher H1 test；
- 在确认无剩余 import 后删除旧 `search_providers/`（Tavily/fallback 残留源码）。

如基线漂移，脚本会直接失败，不会模糊套 patch。

## Cursor 必跑的 focused tests

```bash
cd backend
uv run pytest -q \
  tests/agent/test_research_usage_accounting.py \
  tests/agent/test_research_runtime.py \
  tests/agent/test_research_routing.py \
  tests/agent/test_deep_research_workflow.py \
  tests/agent/test_harness_capabilities.py \
  tests/agent/test_runtime_protection_e2e.py \
  tests/agent/test_tool_timeout_closure.py \
  tests/agent/test_travel_tools.py
```

其中最重要的新增验收是：

- Main 3 model / 2 tool + Worker 7 model / 6 tool：**运行成功**，Product usage 统计整棵树 10 model、至少 8 tool；证明 role limits 隔离且 accounting 聚合。
- Main 第二次 `run_workflow`：Tool call 可被模型提出，但 **host 不执行第二次 Worker**。
- fake source URL、未执行的 `get_weather`、失败的 `get_weather`：都 **不能保留 verified**。
- POI Worker 的真实 `image_search` 结果可以进入 `media` 并流到 Main；weather-only Worker 不搜图。

## 全量验收

```bash
cd backend
uv run pytest -q
uv run ruff check app tests
uv run mypy app
```

如果项目 CI 使用仓库脚本，也应再跑对应 `backend/scripts/test.sh` / `lint.sh`。

## 本包在生成环境已经做的检查

- S1 输入 ZIP SHA256 已核对：`a380d3e0...094a0`。
- 所有 S2 Python 文件：`compileall` 通过。
- S2 apply script：`py_compile` 通过。
- 本生成环境 **没有** Python 3.14.6、`pydantic-ai==2.28.0`、Harness 0.21.0、DDGS 完整运行依赖，因此没有伪称这里已经执行项目 pytest。

## 状态

- `READY_FOR_CURSOR = YES`
- `READY_FOR_COMMIT = NO`，直到 Cursor 在真实项目环境完成 `uv lock`、focused tests、full backend tests/lint。
- 前端 itinerary card / POI 图片结构化展示仍是后续阶段，不属于本 S2 backend closure。
