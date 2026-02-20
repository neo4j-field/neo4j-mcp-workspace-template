"""Job manager for background entity extraction.

Manages an in-memory store of extraction jobs with status tracking,
progress reporting, and cancellation support.

Adapted from the lexical graph MCP server's job manager.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from enum import Enum
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field

from .models import PassType

logger = structlog.get_logger()


class JobStatus(str, Enum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    WRITING = "writing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExtractionJobInfo(BaseModel):
    """Tracks the full lifecycle of a background extraction job."""

    id: str = Field(..., description="Unique job identifier")
    status: JobStatus = Field(default=JobStatus.QUEUED)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    # Parameters
    model: str = Field(..., description="LLM model used")
    pass_type: PassType = Field(default=PassType.FULL)
    pass_number: int = Field(default=1)

    # Chunk counts
    total_chunks: int = Field(default=0)
    text_chunks: int = Field(default=0)
    vlm_chunks: int = Field(default=0)

    # Progress
    chunks_completed: int = 0
    chunks_failed: int = 0
    entities_extracted: int = 0
    relationships_extracted: int = 0
    batches_written: int = 0

    # Results
    entities_created: int = 0
    relationships_created: int = 0
    extracted_from_created: int = 0
    error: Optional[str] = None

    @property
    def chunks_remaining(self) -> int:
        return self.total_chunks - self.chunks_completed - self.chunks_failed

    @property
    def elapsed_seconds(self) -> float:
        return round(time.time() - self.created_at, 1)

    @property
    def estimated_remaining_seconds(self) -> Optional[float]:
        if self.chunks_completed == 0:
            return None
        avg_per_chunk = self.elapsed_seconds / self.chunks_completed
        remaining = self.chunks_remaining
        if remaining <= 0:
            return 0.0
        return round(avg_per_chunk * remaining, 1)

    @property
    def message(self) -> str:
        if self.status == JobStatus.QUEUED:
            return (
                f"Queued: {self.total_chunks} chunks "
                f"({self.text_chunks} text, {self.vlm_chunks} visual) "
                f"with {self.model}"
            )
        elif self.status in (JobStatus.EXTRACTING, JobStatus.WRITING):
            progress = f"{self.chunks_completed}/{self.total_chunks} chunks"
            entities = f"{self.entities_extracted} entities, {self.relationships_extracted} rels"
            eta = self.estimated_remaining_seconds
            eta_str = f" - ~{_format_duration(eta)} remaining" if eta is not None else ""
            return f"{self.status.value}: {progress} ({entities}){eta_str}"
        elif self.status == JobStatus.COMPLETE:
            dur = _format_duration(self.elapsed_seconds)
            return (
                f"Complete: {self.entities_created} entities, "
                f"{self.relationships_created} relationships from "
                f"{self.chunks_completed} chunks in {dur}"
            )
        elif self.status == JobStatus.FAILED:
            return f"Failed: {self.error or 'unknown error'}"
        elif self.status == JobStatus.CANCELLED:
            return f"Cancelled after {self.chunks_completed}/{self.total_chunks} chunks."
        return self.status.value

    def to_status_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "job_id": self.id,
            "status": self.status.value,
            "model": self.model,
            "pass_type": self.pass_type.value,
            "pass_number": self.pass_number,
            "elapsed_seconds": self.elapsed_seconds,
            "estimated_remaining_seconds": self.estimated_remaining_seconds,
            "total_chunks": self.total_chunks,
            "text_chunks": self.text_chunks,
            "vlm_chunks": self.vlm_chunks,
            "chunks_completed": self.chunks_completed,
            "chunks_failed": self.chunks_failed,
            "chunks_remaining": self.chunks_remaining,
            "entities_extracted": self.entities_extracted,
            "relationships_extracted": self.relationships_extracted,
            "batches_written": self.batches_written,
            "message": self.message,
        }
        if self.status == JobStatus.COMPLETE:
            d["entities_created"] = self.entities_created
            d["relationships_created"] = self.relationships_created
            d["extracted_from_created"] = self.extracted_from_created
        if self.error:
            d["error"] = self.error
        return d


class JobManager:
    """In-memory manager for background extraction jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, ExtractionJobInfo] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def create_job(
        self,
        model: str,
        total_chunks: int,
        text_chunks: int,
        vlm_chunks: int,
        pass_type: PassType = PassType.FULL,
        pass_number: int = 1,
    ) -> ExtractionJobInfo:
        job_id = uuid.uuid4().hex[:12]
        job = ExtractionJobInfo(
            id=job_id,
            model=model,
            total_chunks=total_chunks,
            text_chunks=text_chunks,
            vlm_chunks=vlm_chunks,
            pass_type=pass_type,
            pass_number=pass_number,
        )
        self._jobs[job_id] = job
        logger.info(
            "Extraction job created",
            job_id=job_id,
            model=model,
            total=total_chunks,
            text=text_chunks,
            vlm=vlm_chunks,
        )
        return job

    def get_job(self, job_id: str) -> Optional[ExtractionJobInfo]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[ExtractionJobInfo]:
        return list(self._jobs.values())

    def register_task(self, job_id: str, task: asyncio.Task) -> None:
        self._tasks[job_id] = task

    def update_status(self, job_id: str, status: JobStatus, **kwargs: Any) -> None:
        job = self._jobs.get(job_id)
        if job:
            job.status = status
            job.updated_at = time.time()
            for k, v in kwargs.items():
                if hasattr(job, k):
                    setattr(job, k, v)

    def update_progress(self, job_id: str, **kwargs: Any) -> None:
        job = self._jobs.get(job_id)
        if job:
            job.updated_at = time.time()
            for k, v in kwargs.items():
                if hasattr(job, k):
                    setattr(job, k, v)

    def cancel_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED):
            return False

        job.status = JobStatus.CANCELLED
        job.updated_at = time.time()

        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            logger.info("Extraction job cancelled", job_id=job_id)
            return True

        return True

    def cleanup_finished(self, max_age_seconds: float = 3600) -> int:
        now = time.time()
        to_remove = [
            jid
            for jid, job in self._jobs.items()
            if job.status
            in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED)
            and (now - job.updated_at) > max_age_seconds
        ]
        for jid in to_remove:
            del self._jobs[jid]
            self._tasks.pop(jid, None)
        return len(to_remove)


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f}m{seconds % 60:.0f}s"
    hours = minutes / 60
    return f"{hours:.0f}h{minutes % 60:.0f}m"
