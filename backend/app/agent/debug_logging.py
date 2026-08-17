"""Temporary runtime evidence sink for the active debug session."""

from __future__ import annotations

import json
import time
from typing import Any

_DEBUG_LOG = r"D:\application\.cursor\debug-01bd8fd5-a4b2-4c10-934e-e8beb44ad423.log"
_SESSION_ID = "01bd8fd5-a4b2-4c10-934e-e8beb44ad423"


def debug_runtime_log(
    *,
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, Any],
    run_id: str = "pre-fix",
) -> None:
    try:
        timestamp = int(time.time() * 1000)
        with open(_DEBUG_LOG, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "sessionId": _SESSION_ID,
                        "id": f"log_{timestamp}_{location}",
                        "timestamp": timestamp,
                        "location": location,
                        "message": message,
                        "data": data,
                        "runId": run_id,
                        "hypothesisId": hypothesis_id,
                    },
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )
    except Exception:
        pass
