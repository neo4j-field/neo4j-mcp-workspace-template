"""Job manager for background processing of lexical graph creation.

Manages an in-memory store of processing jobs with status tracking,
progress reporting, and cancellation support.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from enum import Enum
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class JobStatus(str, Enum):
    QUEUED = "queued"
    PARSING = "parsing"
    WRITING = "writing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobInfo(BaseModel):
    """Tracks the full lifecycle of a background processing job."""

    id: str = Field(..., description="Unique job identifier")
    status: JobStatus = Field(default=JobStatus.QUEUED)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    # Parameters
    path: str = Field(..., description="PDF file or folder path")
    parse_mode: str = Field(..., description="pymupdf, docling, or page_image")
    is_folder: bool = Field(default=False)

    # Pre-flight info
    files_total: int = Field(default=1)
    total_pages_expected: int = Field(default=0)

    # Progress tracking
    current_file: Optional[str] = None
    current_file_pages: int = 0
    current_stage: Optional[str] = None
    files_completed: int = 0
    files_failed: int = 0
    total_pages_processed: int = 0
    total_elements_extracted: int = 0

    # Results (populated on completion)
    documents_created: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    @property
    def files_remaining(self) -> int:
        return self.files_total - self.files_completed - self.files_failed

    @property
    def elapsed_seconds(self) -> float:
        return round(time.time() - self.created_at, 1)

    @property
    def estimated_remaining_seconds(self) -> Optional[float]:
        """Estimate remaining time based on average time per completed doc."""
        if self.files_completed == 0:
            return None
        avg_per_doc = self.elapsed_seconds / self.files_completed
        remaining = self.files_remaining
        if remaining <= 0:
            return 0.0
        return round(avg_per_doc * remaining, 1)

    @property
    def message(self) -> str:
        """Human-readable one-line summary."""
        if self.status == JobStatus.QUEUED:
            return (
                f"Queued: {self.files_total} file(s) "
                f"({self.total_pages_expected} pages) with {self.parse_mode} mode."
            )
        elif self.status in (JobStatus.PARSING, JobStatus.WRITING):
            stage = self.current_stage or self.status.value
            file_info = f" {self.current_file}" if self.current_file else ""
            page_info = f" ({self.current_file_pages} pages)" if self.current_file_pages else ""
            progress = f"{self.files_completed}/{self.files_total} documents complete"
            eta = self.estimated_remaining_seconds
            eta_str = f" - ~{_format_duration(eta)} remaining" if eta is not None else ""
            return f"{stage.capitalize()}{file_info}{page_info} - {progress}{eta_str}"
        elif self.status == JobStatus.COMPLETE:
            dur = _format_duration(self.elapsed_seconds)
            fails = f" {self.files_failed} failed." if self.files_failed else ""
            return (
                f"Complete: {self.files_completed}/{self.files_total} documents "
                f"({self.total_pages_processed} pages, "
                f"{self.total_elements_extracted} elements) in {dur}.{fails}"
            )
        elif self.status == JobStatus.FAILED:
            return f"Failed: {self.error or 'unknown error'}"
        elif self.status == JobStatus.CANCELLED:
            return f"Cancelled after {self.files_completed}/{self.files_total} documents."
        return self.status.value

    def to_status_dict(self) -> dict[str, Any]:
        """Serialize for the check_processing_status tool response."""
        d: dict[str, Any] = {
            "job_id": self.id,
            "status": self.status.value,
            "parse_mode": self.parse_mode,
            "is_folder": self.is_folder,
            "elapsed_seconds": self.elapsed_seconds,
            "estimated_remaining_seconds": self.estimated_remaining_seconds,
            "files_total": self.files_total,
            "files_completed": self.files_completed,
            "files_failed": self.files_failed,
            "files_remaining": self.files_remaining,
            "current_file": self.current_file,
            "current_file_pages": self.current_file_pages,
            "current_stage": self.current_stage,
            "total_pages_processed": self.total_pages_processed,
            "total_elements_extracted": self.total_elements_extracted,
            "message": self.message,
        }
        if self.errors:
            d["errors"] = self.errors
        if self.status == JobStatus.COMPLETE:
            d["documents_created"] = self.documents_created
        if self.result:
            d["result"] = self.result
        if self.error:
            d["error"] = self.error
        return d


class JobManager:
    """In-memory manager for background processing jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobInfo] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def create_job(
        self,
        path: str,
        parse_mode: str,
        is_folder: bool,
        files_total: int,
        total_pages_expected: int,
    ) -> JobInfo:
        """Create a new job and return it."""
        job_id = uuid.uuid4().hex[:12]
        job = JobInfo(
            id=job_id,
            path=path,
            parse_mode=parse_mode,
            is_folder=is_folder,
            files_total=files_total,
            total_pages_expected=total_pages_expected,
        )
        self._jobs[job_id] = job
        logger.info("Job created", job_id=job_id, parse_mode=parse_mode,
                     files=files_total, pages=total_pages_expected)
        return job

    def get_job(self, job_id: str) -> Optional[JobInfo]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[JobInfo]:
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
        """Cancel a job. Returns True if cancellation was initiated."""
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED):
            return False

        job.status = JobStatus.CANCELLED
        job.updated_at = time.time()

        # Cancel the asyncio task
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            logger.info("Job cancelled", job_id=job_id)
            return True

        return True

    def cleanup_finished(self, max_age_seconds: float = 3600) -> int:
        """Remove finished jobs older than max_age_seconds. Returns count removed."""
        now = time.time()
        to_remove = [
            jid for jid, job in self._jobs.items()
            if job.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED)
            and (now - job.updated_at) > max_age_seconds
        ]
        for jid in to_remove:
            del self._jobs[jid]
            self._tasks.pop(jid, None)
        return len(to_remove)


def _format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f}m{seconds % 60:.0f}s"
    hours = minutes / 60
    return f"{hours:.0f}h{minutes % 60:.0f}m"
