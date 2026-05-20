import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger("nexus.events")

_handlers: dict[str, list[Callable]] = {}


def on(event: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        _handlers.setdefault(event, []).append(fn)
        return fn
    return decorator


def emit(event: str, **data: Any) -> None:
    payload = {"event": event, "ts": datetime.now(timezone.utc).isoformat(), **data}
    logger.info(json.dumps(payload))
    for handler in _handlers.get(event, []):
        try:
            handler(**data)
        except Exception as e:
            logger.error(f"Event handler error [{event}]: {e}")
