"""Structured logs that Cloud Logging understands.

Every log line is one JSON object on stdout. Cloud Run sends stdout to Cloud
Logging, which reads "severity" and "message" and keeps the other fields
searchable, for example:

    jsonPayload.request_id="3f2a9c1b7d4e"     every step of one chat
    jsonPayload.user_id="vikas"               everything one user did
    severity>=WARNING                         only problems

Prompts and answers are NOT logged unless LOG_PROMPTS=true, because users can
type personal data. Locally, LOG_FORMAT=text gives plain readable lines.
"""
import json
import logging
import os
import sys
from contextvars import ContextVar

# Set once per HTTP request by the middleware in main.py; every log line
# written while handling that request carries it.
request_id: ContextVar[str] = ContextVar("request_id", default="-")

LOG_PROMPTS = os.getenv("LOG_PROMPTS", "").lower() == "true"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": request_id.get(),
            **getattr(record, "fields", {}),
        }
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = " ".join(f"{k}={v}" for k, v in getattr(record, "fields", {}).items())
        line = f"{record.levelname:<7} [{request_id.get()}] {record.getMessage()} {fields}".rstrip()
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging() -> None:
    """Send all logs (ours and ADK's) to stdout in one format."""
    handler = logging.StreamHandler(sys.stdout)
    text = os.getenv("LOG_FORMAT", "json").lower() == "text"
    handler.setFormatter(TextFormatter() if text else JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    # httpx logs every Gemini/HTTP call at INFO; our own lines already cover them.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def log(logger: logging.Logger, level: int, message: str, **fields) -> None:
    """Write one log line with extra searchable fields."""
    logger.log(level, message, extra={"fields": fields})


def short(value, limit: int = 500) -> str:
    """Keep big values (SQL, tool results) from flooding the logs."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "…"
