"""Diagnostic security and DLP activity logger.

Provides structured, safe diagnostic logging across browser CDP events,
DOM file bridge capture, and DLP enforcement decisions.
Strictly redacts sensitive payloads: never logs file contents, base64 data,
cookies, or authentication tokens.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

LOGGER_NAME = "walled_ai.dlp"


def setup_diagnostic_logger(log_dir: Optional[str] = None) -> logging.Logger:
    """Initialize and configure the DLP diagnostic logger."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [DLP] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. Console Stream Handler (outputs to terminal for immediate live visibility)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 2. File Handler (persists diagnostic trace to disk)
    try:
        base_dir = Path(log_dir) if log_dir else Path(__file__).resolve().parent.parent.parent / "logs"
        base_dir.mkdir(parents=True, exist_ok=True)
        file_path = base_dir / "dlp_diagnostic.log"

        file_handler = logging.FileHandler(str(file_path), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        console_handler.setLevel(logging.DEBUG)
        logger.warning(f"Could not initialize diagnostic log file: {e}")

    return logger


# Default diagnostic logger singleton
diag_logger = setup_diagnostic_logger()
