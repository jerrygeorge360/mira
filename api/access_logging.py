"""Access-log filtering for internal container health probes."""

from __future__ import annotations

import logging


class SuccessfulHealthCheckFilter(logging.Filter):
    """Hide successful health probes while preserving failures and user traffic."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        path = str(args[2]).partition("?")[0]
        status = args[4]
        if not isinstance(status, (str, int)):
            return True
        try:
            status_code = int(status)
        except ValueError:
            return True
        return path != "/health" or status_code >= 400


def install_health_access_filter() -> None:
    """Install the Uvicorn access filter once for the current process."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, SuccessfulHealthCheckFilter) for item in logger.filters):
        logger.addFilter(SuccessfulHealthCheckFilter())
