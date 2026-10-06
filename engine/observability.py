"""Small structured event logger. Callers provide controlled, non-secret fields."""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("ddm")


def emit(event, **fields):
    payload = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    logger.warning(json.dumps(payload, ensure_ascii=True, allow_nan=False))
