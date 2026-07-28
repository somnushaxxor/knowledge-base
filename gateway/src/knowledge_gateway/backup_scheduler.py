"""Periodic Git backup scheduler for the Knowledge Gateway."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import KnowledgeGateway

logger = logging.getLogger(__name__)


class BackupScheduler:
    """Daemon thread that periodically commits and pushes the OKF bundle."""

    def __init__(self, service: "KnowledgeGateway"):
        self.service = service
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        hours = self.service.settings.backup_interval_hours
        if hours <= 0:
            logger.info("periodic Git backup disabled (KB_BACKUP_INTERVAL_HOURS=%s)", hours)
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="kb-backup-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("periodic Git backup every %s hour(s)", hours)

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        seconds = self.service.settings.backup_interval_hours * 3600
        while not self._stop.wait(seconds):
            try:
                result = self.service.run_backup()
                logger.info("scheduled backup finished: %s", result)
            except Exception:
                logger.exception("scheduled backup failed")
