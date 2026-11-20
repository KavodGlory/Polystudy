"""Background jobs for file translation.

Translating a long PDF can take minutes, longer than a web request should stay open. So the
upload route starts a job in a background thread and returns a job id at once. The page then
polls the status route to show a progress bar and, when done, offers the download.

Jobs live in memory only: they disappear when the server restarts or after an hour.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field

from translator.errors import DocumentError, TranslationError

log = logging.getLogger(__name__)


class TooBusy(Exception):
    """Too many translations are already running."""


@dataclass
class Job:
    id: str
    filename: str
    target: str
    total: int
    status: str = "running"          # running | done | error
    done: int = 0
    error: str = ""
    result: object = None            # a DocumentResult when finished
    created: float = field(default_factory=time.time)


class JobStore:
    def __init__(self, max_running: int = 3, ttl_seconds: int = 3600):
        self.max_running = max_running
        self.ttl = ttl_seconds
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def _purge(self) -> None:
        cutoff = time.time() - self.ttl
        for job_id in [i for i, j in self._jobs.items() if j.created < cutoff and j.status != "running"]:
            del self._jobs[job_id]

    def start(self, work, filename: str, target: str, total: int) -> str:
        """Run work(progress) in a thread. `progress(done, total)` updates the bar."""
        with self._lock:
            self._purge()
            if sum(j.status == "running" for j in self._jobs.values()) >= self.max_running:
                raise TooBusy("Several translations are running. Please try again in a minute.")
            job = Job(secrets.token_urlsafe(16), filename, target, total)
            self._jobs[job.id] = job

        def progress(done: int, total_: int) -> None:
            job.done, job.total = done, total_

        def run() -> None:
            try:
                job.result = work(progress)
                job.status = "done"
            except (TranslationError, DocumentError) as exc:
                job.error, job.status = str(exc), "error"
            except Exception:                                  # a bug: log it, show a generic message
                log.exception("File translation failed")
                job.error, job.status = "Something went wrong while translating this file.", "error"

        threading.Thread(target=run, daemon=True).start()
        return job.id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)
