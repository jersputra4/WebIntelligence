"""Logging setup. Never log secrets: the API key is redacted from any message."""
from __future__ import annotations

import logging
import sys

_configured = False


class RedactSecretsFilter(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secrets:
            message = record.getMessage()
            for secret in self._secrets:
                message = message.replace(secret, "***")
            record.msg, record.args = message, None
        return True


def setup_logging(level: str = "INFO", secrets: list[str] | None = None) -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    handler.addFilter(RedactSecretsFilter(secrets or []))
    root = logging.getLogger("intel")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False
    # httpx logs full request URLs (which contain the token query param) at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"intel.{name}")
