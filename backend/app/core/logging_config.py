"""Logging setup: one readable console format for the whole application."""

import logging
import logging.config

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(level: str = "INFO") -> None:
    """Configure logging once. Safe to call multiple times."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"standard": {"format": _LOG_FORMAT}},
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "standard"},
            },
            "loggers": {
                "app": {"handlers": ["console"], "level": level.upper(), "propagate": False},
            },
        }
    )
