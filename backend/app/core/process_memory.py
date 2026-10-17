"""
app/core/process_memory.py

Resident memory (RSS) of this process, read from /proc/self/status (Linux only, no
dependency), logged at startup, when a gunicorn worker starts and after each scoring.

The numbers exist to check the app against Render's 512 MB on the first deploy
(docs/deploy_phase3.md). The line is INFO on its own logger, forced to INFO so it is
visible at the production LOG_LEVEL of WARNING. It carries the pid, the stage and the
RSS, nothing else.
"""
import logging
import os
from pathlib import Path

logger = logging.getLogger("app.memory")
logger.setLevel(logging.INFO)

_PROC_STATUS = Path("/proc/self/status")


def rss_mb(status_path: Path = _PROC_STATUS) -> float | None:
    """The process's resident set size in MB, or None where /proc is not available."""
    try:
        for line in Path(status_path).read_text().splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def log_rss(stage: str) -> None:
    rss = rss_mb()
    if rss is not None:
        logger.info("Process memory", extra={"stage": stage, "pid": os.getpid(), "rss_mb": rss})
