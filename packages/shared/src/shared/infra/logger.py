"""
Configure the logger to output JSON logs.

Reference:
https://github.com/sheshbabu/fastapi-structured-json-logging-demo/blob/0ee5f2def471dac94f653951f66bfbea5b81364b/src/logger.py
"""

import json
import logging
from logging import Formatter

from shared.settings import settings


class JsonFormatter(Formatter):
    def __init__(self):
        super().__init__()

    def format(self, record) -> str:  # type: ignore
        json_record = {}
        json_record["timestamp"] = self.formatTime(record, self.datefmt)
        json_record["levelname"] = record.levelname
        json_record["name"] = record.name
        json_record["message"] = record.getMessage()
        json_record["levelno"] = record.levelno
        json_record["filename"] = record.filename
        json_record["funcname"] = record.funcName
        if "request" in record.__dict__:
            json_record["request"] = record.__dict__["request"]
        if "response" in record.__dict__:
            json_record["response"] = record.__dict__["response"]
        if record.levelno == logging.ERROR and record.exc_info:
            json_record["error"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in json_record and key not in (
                "args",
                "msg",
                "levelno",
                "levelname",
                "exc_info",
                "exc_text",
                "stack_info",
            ):
                json_record[key] = value
        return json.dumps(json_record)


# Every attribute a plain LogRecord carries on its own, plus the two a Formatter adds while
# rendering (`message`, `asctime`) — diffed against record.__dict__ below to isolate exactly the
# fields a caller passed via `extra=`, nothing from the record's own bookkeeping.
_RESERVED_LOG_RECORD_ATTRS = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
    ).__dict__.keys()
) | {"message", "asctime"}


class DevFormatter(Formatter):
    """Human-readable formatter for dev/test: the usual one-line message, plus a compact JSON
    tail of the real ``extra=`` fields, so they're inspectable locally without prod-like JSON
    output. Exception tracebacks (via ``logger.exception``) still render as usual, above the tail.
    """

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s [%(levelname)s] - %(name)s.%(funcName)s: %(message)s"
        )

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_LOG_RECORD_ATTRS
        }
        if not extras:
            return base
        try:
            extras_json = json.dumps(extras, default=str)
        except TypeError:
            extras_json = str(extras)
        return f"{base} | {extras_json}"


def _build_handler(*, prod_like: bool) -> logging.StreamHandler:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if prod_like else DevFormatter())
    return handler


logger = logging.getLogger("eventhub")
logger.handlers = [_build_handler(prod_like=settings.is_prod_like())]
# Own handler covers every level; propagating up as well would double-print if anything else
# (e.g. a test runner or ASGI server) ever attaches a handler to the root logger.
logger.propagate = False

logger.setLevel(settings.LOGGING_LEVEL)

# disable uvicorn access logs because we are using our own logger middleware in main.py
logging.getLogger("uvicorn.access").disabled = True

logging.getLogger("httpx").setLevel(logging.WARNING)
