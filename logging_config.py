"""
Structured (JSON) logging setup.

Plain print()/traceback.print_exc() calls produce unstructured text that's
painful to search once there's real production traffic — you can't filter
"show me all 500s for user X in the last hour" against a wall of print
statements. This gives every log line a consistent JSON shape instead:
timestamp, level, message, and whatever extra fields a call site attaches
(request path, user id, status code, etc).

In local dev (FLASK_DEBUG=1), logs stay human-readable instead — nobody
wants to read raw JSON while developing.
"""

import logging
import os
import sys

try:
    from pythonjsonlogger.json import JsonFormatter
except ImportError:
    # Older versions of python-json-logger use this import path instead.
    from pythonjsonlogger.jsonlogger import JsonFormatter


def configure_logging(app):
    is_debug = os.environ.get("FLASK_DEBUG") == "1"

    handler = logging.StreamHandler(sys.stdout)

    if is_debug:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        )
    else:
        formatter = JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )

    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.DEBUG if is_debug else logging.INFO)

    # Quiet down noisy third-party loggers so they don't drown out our
    # own log lines at INFO level.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    app.logger.handlers = [handler]
    app.logger.setLevel(logging.DEBUG if is_debug else logging.INFO)

    return app.logger
