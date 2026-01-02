from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

logger = logging.getLogger("broker.trading")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"broker.{name}")


def log_decision(
    symbol: str,
    decision_type: str,
    decision: str,
    reason: str,
    confidence: float | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "decision_type": decision_type,
        "decision": decision,
        "reason": reason,
        "confidence": confidence,
        "metadata": dict(metadata) if metadata else {},
    }
    logger.info(json.dumps(entry))
