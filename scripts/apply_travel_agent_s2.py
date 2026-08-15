#!/usr/bin/env python3
"""Apply the S2 Deep Research closure changes that touch files outside the overlay.

Run from the repository root *after* extracting this ZIP. The script is fail-closed:
it only patches the exact travel_agent_v8 baseline shapes that S2 was built against.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

BASE_HEAD = "ab0738def24828b71c5c9ff60bf39bd2042414c2"
EXPECTED_EXECUTOR_GIT_BLOB = "d5ee0947471480bd8c735268e20cae556b6fc910"
EXECUTOR = Path("backend/app/agent/pydantic_executor.py")
OLD_H1 = Path("backend/tests/agent/test_optional_researcher_routing.py")
OLD_SEARCH_PROVIDERS = Path("backend/app/agent/tools/search_providers")
REQUIRED_OVERLAY = (
    Path("backend/app/agent/research_runtime.py"),
    Path("backend/app/agent/capabilities/research_guard.py"),
    Path("backend/tests/agent/test_research_runtime.py"),
    Path("backend/tests/agent/test_research_usage_accounting.py"),
)


def fail(message: str) -> None:
    raise SystemExit(f"S2 apply aborted: {message}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        fail(f"expected exactly one {label} anchor, found {count}; repository drifted")
    return text.replace(old, new, 1)



def verify_overlay() -> None:
    missing = [str(path) for path in REQUIRED_OVERLAY if not path.exists()]
    if missing:
        fail("S2 overlay was not extracted first; missing: " + ", ".join(missing))
    pyproject = Path("backend/pyproject.toml").read_text(encoding="utf-8")
    required_pins = (
        '"pydantic-ai==2.28.0"',
        '"pydantic-ai-harness[skills,dynamic-workflow]==0.21.0"',
        '"ddgs>=9.14.4,<10.0.0"',
    )
    for pin in required_pins:
        if pin not in pyproject:
            fail(f"missing expected dependency pin: {pin}")
    if "tavily" in pyproject.casefold():
        fail("Tavily dependency is still present in backend/pyproject.toml")


def verify_baseline() -> None:
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
        blob = subprocess.check_output(
            ["git", "hash-object", str(EXECUTOR)], text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        fail(f"cannot verify git baseline: {exc}")
    if head != BASE_HEAD:
        fail(f"expected HEAD {BASE_HEAD}, got {head}")
    if blob != EXPECTED_EXECUTOR_GIT_BLOB:
        fail(
            f"expected pydantic_executor blob {EXPECTED_EXECUTOR_GIT_BLOB}, got {blob}"
        )


def patch_executor() -> None:
    if not EXECUTOR.exists():
        fail(f"missing {EXECUTOR}")
    text = EXECUTOR.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "from app.agent.prompts import MAIN_TRAVEL_INSTRUCTIONS\nfrom app.agent.usage import AgentModelCallUsage, AgentTokenUsage, AgentUsage\n",
        "from app.agent.prompts import MAIN_TRAVEL_INSTRUCTIONS\n"
        "from app.agent.research_runtime import (\n"
        "    ResearchRequestState,\n"
        "    bind_research_request_state,\n"
        ")\n"
        "from app.agent.usage import AgentModelCallUsage, AgentTokenUsage, AgentUsage\n",
        "research runtime import",
    )

    start = text.find("def _to_agent_usage(\n")
    end = text.find("\ndef _to_reasoning_summary", start)
    if start < 0 or end < 0:
        fail("cannot locate _to_agent_usage function")
    new_usage = '''def _to_agent_usage(
    result: AgentRunResult[Any],
    *,
    logical_model: str,
    research_state: ResearchRequestState | None = None,
) -> AgentUsage:
    """Map Main + isolated Research Worker usage into one Product contract.

    Harness keeps Worker budgets isolated with ``forward_usage=False``. Worker
    responses are therefore captured by request-scoped PydanticAI hooks and merged
    here explicitly. This preserves Main's 8/6 role limit while Product billing,
    quota analysis, and observability still see the complete request tree.
    """
    main_responses = tuple(
        message
        for message in result.new_messages()
        if isinstance(message, ModelResponse)
    )
    worker_runs = tuple(research_state.worker_runs) if research_state is not None else ()
    all_responses = (
        *main_responses,
        *(response for run in worker_runs for response in run.responses),
    )
    model_calls = tuple(
        _to_agent_model_call_usage(
            message,
            call_index=call_index,
            logical_model=logical_model,
        )
        for call_index, message in enumerate(all_responses)
    )

    main_unattributed = max(0, result.usage.requests - len(main_responses))
    worker_requests = sum(run.requests for run in worker_runs)
    worker_attributed = sum(len(run.responses) for run in worker_runs)
    worker_unattributed = max(0, worker_requests - worker_attributed)
    worker_tool_calls = sum(run.tool_calls for run in worker_runs)

    return AgentUsage(
        model_calls=model_calls,
        tool_calls=result.usage.tool_calls + worker_tool_calls,
        unattributed_model_requests=main_unattributed + worker_unattributed,
    )

'''
    text = text[:start] + new_usage + text[end + 1 :]

    old_execute = '''        message_history = _to_model_messages(request)
        try:
            result = await self._agent.run(
                request.message,
                message_history=message_history,
                run_id=str(request.request_id),
                usage_limits=_main_usage_limits(),
            )
'''
    new_execute = '''        message_history = _to_model_messages(request)
        research_state = ResearchRequestState()
        try:
            with bind_research_request_state(research_state):
                result = await self._agent.run(
                    request.message,
                    message_history=message_history,
                    run_id=str(request.request_id),
                    usage_limits=_main_usage_limits(),
                )
'''
    text = replace_once(text, old_execute, new_execute, "non-stream request binding")
    text = replace_once(
        text,
        "usage=_to_agent_usage(result, logical_model=self._logical_model),",
        "usage=_to_agent_usage(\n"
        "                result,\n"
        "                logical_model=self._logical_model,\n"
        "                research_state=research_state,\n"
        "            ),",
        "non-stream usage merge",
    )

    text = replace_once(
        text,
        "    reasoning_timer = _ReasoningDurationTracker()\n"
        "    stream_error_code: AgentExecutionErrorCode | None = None\n",
        "    reasoning_timer = _ReasoningDurationTracker()\n"
        "    stream_error_code: AgentExecutionErrorCode | None = None\n"
        "    research_state = ResearchRequestState()\n",
        "stream research state",
    )
    text = replace_once(
        text,
        '''                    usage=_to_agent_usage(
                        result, logical_model=settings.LLM_LOGICAL_MODEL
                    ),
''',
        '''                    usage=_to_agent_usage(
                        result,
                        logical_model=settings.LLM_LOGICAL_MODEL,
                        research_state=research_state,
                    ),
''',
        "stream usage merge",
    )

    old_classified = '''    async def _classified_native_events() -> AsyncIterator[Any]:
        nonlocal stream_error_code
        try:
            async for event in native_events:
                yield event
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            stream_error_code = "MODEL_TIMEOUT"
            raise
        except ModelAPIError as exc:
            stream_error_code = _product_safe_model_error(exc).code
            raise
        except UsageLimitExceeded:
            stream_error_code = "MODEL_CALL_LIMIT_REACHED"
            raise
'''
    new_classified = '''    async def _classified_native_events() -> AsyncIterator[Any]:
        nonlocal stream_error_code
        # Bind while the native run is actually driven. asyncio child tasks spawned
        # by DynamicWorkflow inherit this ContextVar, but their usage counters remain
        # independent because Harness still receives ``usage=None`` for Workers.
        with bind_research_request_state(research_state):
            try:
                async for event in native_events:
                    yield event
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                stream_error_code = "MODEL_TIMEOUT"
                raise
            except ModelAPIError as exc:
                stream_error_code = _product_safe_model_error(exc).code
                raise
            except UsageLimitExceeded:
                stream_error_code = "MODEL_CALL_LIMIT_REACHED"
                raise
'''
    text = replace_once(text, old_classified, new_classified, "stream request binding")

    EXECUTOR.write_text(text, encoding="utf-8")


def remove_stale_h1() -> None:
    # Its behavioral cases are migrated into test_research_routing.py. Keeping the
    # old Optional Researcher suite would retain imports for the removed delegation API.
    if OLD_H1.exists():
        OLD_H1.unlink()


def remove_obsolete_search_providers() -> None:
    # S2 web_search is DDGS-only. Fail if any live Python module still imports the
    # old provider layer; only then remove it so deletion cannot create a hidden break.
    offenders: list[str] = []
    backend = Path("backend")
    for path in backend.rglob("*.py"):
        if path == OLD_H1 or OLD_SEARCH_PROVIDERS in path.parents:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "app.agent.tools.search_providers" in source:
            offenders.append(str(path))
    if offenders:
        fail("old search provider imports remain: " + ", ".join(sorted(offenders)))
    if OLD_SEARCH_PROVIDERS.exists():
        shutil.rmtree(OLD_SEARCH_PROVIDERS)


def main() -> None:
    verify_overlay()
    verify_baseline()
    patch_executor()
    remove_stale_h1()
    remove_obsolete_search_providers()
    digest = hashlib.sha256(EXECUTOR.read_bytes()).hexdigest()
    print(f"S2 executor patched: {EXECUTOR} sha256={digest}")
    print(f"S2 baseline contract: travel_agent_v8 @ {BASE_HEAD}")
    print("Stale Optional Researcher H1 suite removed after migration.")
    print("Obsolete Tavily/fallback search provider source removed.")


if __name__ == "__main__":
    main()
