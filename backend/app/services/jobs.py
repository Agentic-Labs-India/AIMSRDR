from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


ProgressCallback = Callable[[float, str], None]


@dataclass
class ProcessJob:
    id: str
    site_id: str
    status: str = "queued"  # queued | running | completed | failed
    progress: float = 0.0
    step: str = "Queued"
    messages: list[str] = field(default_factory=list)
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "site_id": self.site_id,
            "status": self.status,
            "progress": round(self.progress, 1),
            "step": self.step,
            "messages": self.messages[-12:],
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, ProcessJob] = {}
        self._site_active: dict[str, str] = {}

    def create(self, site_id: str) -> tuple[ProcessJob, bool]:
        """Return (job, created). created=False means an active job already exists."""
        with self._lock:
            existing_id = self._site_active.get(site_id)
            if existing_id:
                existing = self._jobs.get(existing_id)
                if existing and existing.status in {"queued", "running"}:
                    return existing, False
            job = ProcessJob(id=str(uuid.uuid4()), site_id=site_id)
            self._jobs[job.id] = job
            self._site_active[site_id] = job.id
            return job, True

    def get(self, job_id: str) -> ProcessJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(
        self,
        job_id: str,
        *,
        progress: float | None = None,
        step: str | None = None,
        status: str | None = None,
        message: str | None = None,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if progress is not None:
                job.progress = max(0.0, min(100.0, float(progress)))
            if step is not None:
                job.step = step
            if status is not None:
                job.status = status
                if status in {"completed", "failed"}:
                    self._site_active.pop(job.site_id, None)
            if message:
                job.messages.append(message)
            if error is not None:
                job.error = error
            if result is not None:
                job.result = result
            job.updated_at = datetime.now(timezone.utc).isoformat()


JOB_STORE = JobStore()
