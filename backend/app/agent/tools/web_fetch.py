"""Web fetch tool with citable source metadata.

Wraps the official PydanticAI ``WebFetchLocalTool`` (SSRF-protected) so the
model still reads the fetched markdown, while the fetched URL flows to the UI as
a ``source-url`` reference — matching mature products that show *read* sources,
not just search snippets.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_ai import ToolReturn
from pydantic_ai.common_tools.web_fetch import (
    WebFetchLocalTool,
    WebFetchResult,
)
from pydantic_ai.messages import BinaryContent
from pydantic_ai.ui.vercel_ai.response_types import SourceUrlChunk


@lru_cache(maxsize=1)
def _fetcher() -> WebFetchLocalTool:
    return WebFetchLocalTool(
        max_content_length=50_000,
        allow_local_urls=False,
        timeout=30,
    )


async def web_fetch(url: str) -> ToolReturn[str] | BinaryContent:
    """抓取一个网页并把正文转成 markdown 供模型阅读。

    URL 由模型给出；抓取带 SSRF 防护。读取的网页会作为引用来源展示给用户。
    """
    result = await _fetcher().__call__(url)
    if isinstance(result, BinaryContent):
        return result
    return _with_source(result)


def _with_source(result: WebFetchResult) -> ToolReturn[str]:
    return ToolReturn[str](
        return_value=result["content"],
        metadata=[
            SourceUrlChunk(
                source_id="src-fetch",
                url=result["url"],
                title=result["title"] or None,
            )
        ],
    )
