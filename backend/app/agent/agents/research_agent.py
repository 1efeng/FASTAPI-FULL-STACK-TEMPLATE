"""Context-collection research agent for one bounded travel topic.

This agent only SEARCHES + SUMMARIZES. It never verifies, proves, or grades a
fact as verified/conflicting/unresolved. Search exists purely to give Main enough
context; all decision-making stays on Main.
"""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, Model
from pydantic_ai.settings import ModelSettings

from app.agent.context.runtime_clock import runtime_clock_context
from app.agent.research_runtime import ResearchAgentRuntimeCapability
from app.agent.tools.research_tools import build_research_tools
from app.core.config import settings


class EvidenceSource(BaseModel):
    """One source surfaced during context collection."""

    title: str
    url: str
    source_type: str | None = None


class ImageAsset(BaseModel):
    """Display-media candidate retained only for compatibility/presentation."""

    place_name: str
    image_url: str
    thumbnail_url: str | None = None
    source_page_url: str
    title: str | None = None
    width: int | None = None
    height: int | None = None
    source: str | None = None


class ResearchRequest(BaseModel):
    """Minimal handoff from Main asking for enough context on one topic.

    There is no verification contract here: Main only states what context it needs,
    and the child searches + summarizes without judging whether any fact is true.
    """

    objective: str
    title: str | None = Field(default=None, max_length=80)
    context: str | None = None
    constraints: list[str] = Field(default_factory=list)


class ResearchFindings(BaseModel):
    """Compressed context summary returned to Main.

    No verified/conflicting/unresolved grading: the summary reflects what the
    search surfaced; Main decides how to use it.
    """

    topic: str
    summary: str | None = None
    sources: list[EvidenceSource] = Field(default_factory=list)
    media: list[ImageAsset] = Field(default_factory=list)


RESEARCH_AGENT_NAME = "research_agent"
RESEARCH_AGENT_DESCRIPTION = (
    "Search and summarize enough context for one travel planning topic. "
    "Never verifies or proves facts; it only collects context for Main to decide."
)

RESEARCH_AGENT_INSTRUCTIONS = """\
你是 research_agent。你只负责为一个旅行规划主题搜索足够的上下文，并把结果压缩成结构化 ResearchFindings。
你不做最终旅行方案、路线取舍、住宿、预算或最终回答；这些始终由 Main 负责。
你的输出只是“搜索到的背景信息总结”，不是对任何事实成立与否的判定——不要给任何信息打 verified / conflicting / unresolved 标签。

# 搜索目的

- 搜索只用于提供足够的上下文（例如：目的地有哪些选择、大致路线/区域、价格范围、开放时间参考、交通方式概览、当地特色）。
- 不要为了“证明某个判断成立”而搜索，不要反复交叉核验同一事实，不要为了“确认正确”而追加搜索。
- 一次搜索到足够的背景信息后立即停止；不为“资料更完整”继续搜索。

# 方法

1. 围绕 Main 需要上下文的主题，用最少次数的搜索收集背景。
2. 自主决定 Search / Read / Fetch / Maps / Compare / Reason 的顺序，不预先写死研究步骤。
3. 使用 `search_web` 获取背景与来源线索；需要时用 `web_fetch` 读取正文补充背景。
4. POI 名称、坐标、地址、评分、人均、营业时间、入口与附近地点使用 `search_poi` / `get_poi_detail` / `search_nearby`。
5. `search_maps` 提供路线、距离、空间关系和交通方式概览。
6. `get_weather` 只在主题涉及实际旅行日期且需要天气背景时使用。
7. 不要为了“信息更全”做城市、景点、交通或美食的背景普查；只收集与当前主题直接相关的上下文。
8. 只返回 ResearchFindings，不生成最终 itinerary，不调用其他 Agent，也不能调用自身。

# 证据边界

- 引用来源 URL 时，只使用本轮实际搜索/读取到的真实 URL，并列入 `sources`；不得虚构 URL。
- 不得用模型训练记忆补写为“当前事实”；无法从搜索中获得的信息就留空或说明。
- 搜索 snippet 是背景来源；关键背景可打开官方 / primary source 正文补充。
- `media` 仅作为现有兼容字段保留；图片来源不能单独作为事实证据。

# 金额

背景中的价格使用当地货币并明确币种，不自行做最终预算或汇率换算。

# 输出

只返回 ResearchFindings：
- topic：主题
- summary：压缩后的背景总结，直接回答 Main 需要什么样的上下文
- sources：实际用到的来源
- media：少量可选媒体（兼容保留）
"""


def _runtime_clock_instructions() -> str:
    return runtime_clock_context()


def build_research_agent(
    *,
    model: Model | KnownModelName | str | None = None,
) -> Agent[object, ResearchFindings]:
    """Build the reusable iterative research agent used by Main delegation."""

    if model is None:
        raise ValueError("research_agent requires an explicit model")

    return cast(
        Agent[object, ResearchFindings],
        Agent(
            model,
            # Research progress must reach the caller promptly; evidence gathering
            # remains iterative through web search and structured findings.
            model_settings=ModelSettings(
                timeout=settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
                thinking=False,
            ),
            name=RESEARCH_AGENT_NAME,
            description=RESEARCH_AGENT_DESCRIPTION,
            instructions=(RESEARCH_AGENT_INSTRUCTIONS, _runtime_clock_instructions),
            tools=build_research_tools(include_web_search=True),
            capabilities=(ResearchAgentRuntimeCapability(),),
            output_type=ResearchFindings,
            defer_model_check=True,
        ),
    )
