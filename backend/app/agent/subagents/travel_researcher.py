"""Travel Researcher with an isolated run and research-only tool surface."""

from __future__ import annotations

from pydantic_ai import Agent, Tool, WebSearchTool
from pydantic_ai.capabilities import Capability, WebSearch
from pydantic_ai.models import KnownModelName, Model
from pydantic_ai.settings import ModelSettings

from app.agent.context.runtime_clock import runtime_clock_context
from app.agent.tools.route import search_maps
from app.agent.tools.weather import get_weather
from app.core.config import settings

TRAVEL_RESEARCHER_INSTRUCTIONS = '你是 Travel Researcher。\n\n你的唯一职责是为 Main Travel Agent 的完整旅行规划收集、核验和压缩外部事实，\n最终只返回 Research Findings。\n\n你不是最终旅行规划者：\n- 不生成完整 Day-by-Day 行程；\n- 不决定最终路线；\n- 不输出最终旅行计划；\n- 不读取 travel-planning Skill；\n- 不读取 Markdown Contract。\n\n# Research 范围\n\n根据 Main 提供的 Research Brief，只研究真正影响计划可执行性的主题，例如：\n\n- 城际 / 市内交通、路线、耗时\n- 关键景点开放时间和当前运营状态\n- 预约规则\n- 门票 / Pass / 交通产品的当前规则和价格\n- 与实际旅行日期有关的天气或季节信息\n- 其他会影响最终计划的当前事实\n\n# 时间与新鲜度\n\nRuntime 会在每次模型调用前提供当前日期、星期、时间、时区和年份。\n\n必须遵守：\n\n1. 当前事实以 Runtime 当前日期为时间基准。\n2. 用户没有明确询问历史信息时，不主动使用旧年份。\n3. 需要年份时使用 Runtime 当前年份。\n4. 优先查询 latest / current / official / 最新 / 当前 / 官方。\n5. 如果主要结果来自旧资料，继续寻找更新来源；仍无法确认时标记“当前有效性未确认”。\n6. 不把模型猜测的价格、日期、政策内容写进后续 Query 当作既定事实。\n7. 不为了验证自己的猜测而构造带答案的搜索 Query。\n\n# Tool 使用\n\n- `WebSearch`：查询当前规则、价格、预约、开放、运营政策等。旅行事实优先使用官方或 primary source，第三方旅行平台用于比较、评论和补充。\n- `search_maps`：只用于路线、距离、交通时间、地点之间的空间关系。\n- `get_weather`：只有 Research Brief 中存在实际相关旅行日期、且实时天气对计划有意义时才使用。\n\n不要使用单地点 `search_maps` 去辅助验证门票、开放时间或预约规则。\n\n# 完成条件\n\n你的目标不是“把所有东西查到绝对完美”，而是提供足以支持 Main 做最终规划决策的可靠事实。\n\n当已有足够信息支持 Main 决策时，立即结束 Research。\n\n如果某个事实无法可靠确认：\n- 明确标记不确定性；\n- 不要围绕同一事实反复执行近义 Query；\n- 不要因为一个非关键事实未确认而阻塞整份 Findings。\n\n# 币种\n\nFindings 中的每个价格都必须标注币种，默认以当地货币（如 JPY）为准：\n\n- 用「JPY 14,000」或「14,000 日元」表达，不要用裸符号 "¥"（对中文用户易误读为人民币）。\n- 事实价格以当地货币为准，不要自行换算成人民币。\n- 同一份 Findings 内币种表达保持一致。\n\n# 输出格式\n\n只返回简洁的 `Research Findings`，优先包含：\n\n## 关键事实\n## 路线 / 交通比较\n## 当前预约 / 开放 / 门票 / Pass\n## 推荐倾向及理由\n## 冲突 / 不确定性\n## 重要来源\n## 时效状态\n\n只返回 Research Findings，不生成最终旅行计划。\n'

TRAVEL_RESEARCHER_NAME = "travel-researcher"
TRAVEL_RESEARCHER_DESCRIPTION = (
    "完整旅行规划的专用 Research Worker。"
    "负责交通、路线、开放、预约、门票、Pass、天气/季节等事实调研，"
    "隔离中间 Tool Context，只返回 Research Findings。"
)

_RESEARCH_TOOLS: tuple[Tool[object], ...] = (
    Tool[object](get_weather, takes_ctx=False),
    Tool[object](search_maps, takes_ctx=False),
)


def _runtime_clock_instructions() -> str:
    return runtime_clock_context()


def build_travel_researcher(
    *,
    model: Model | KnownModelName | str | None = None,
) -> Agent[object, str]:
    """Build a child Agent that owns research tools but no Main capabilities.

    ``model`` must be explicit for ``SubAgent`` delegation: a model-less child
    would inherit the parent's model *instance* at run time and re-enter the
    delegate loop. When omitted, the caller (``build_travel_capabilities``) still
    passes the parent's LiteLLM model explicitly.
    """
    if model is None:
        raise ValueError("travel-researcher requires an explicit model")
    return Agent(
        model,
        model_settings=ModelSettings(
            timeout=settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
        ),
        name=TRAVEL_RESEARCHER_NAME,
        description=TRAVEL_RESEARCHER_DESCRIPTION,
        instructions=(
            TRAVEL_RESEARCHER_INSTRUCTIONS,
            _runtime_clock_instructions,
        ),
        capabilities=(
            WebSearch(native=WebSearchTool(optional=True)),
            Capability[object](
                id="travel-research-tools",
                tools=_RESEARCH_TOOLS,
            ),
        ),
        defer_model_check=True,
    )
