"""Asynchronous Task Manager for AI Clinical Summarization & Regeneration Jobs."""

from datetime import datetime, timezone
import threading
from typing import Any, Dict, Optional, Tuple
import uuid
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.summary import SummaryTaskModel
from app.schemas.summary import ClinicalSummaryResponse


class SummaryTaskManager:
    """Thread-safe and DB-backed task state tracker for asynchronous background AI summarization jobs."""

    def __init__(self, max_history: int = 500) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._patient_latest_task: Dict[str, str] = {}
        self._max_history = max_history
        self._lock = threading.Lock()

    def _task_model_to_dict(self, model: SummaryTaskModel) -> Dict[str, Any]:
        """Convert a SummaryTaskModel ORM object to task dictionary."""
        summary_obj = None
        if model.summary_json:
            try:
                summary_obj = ClinicalSummaryResponse.model_validate(model.summary_json)
            except Exception:
                summary_obj = model.summary_json

        return {
            "task_id": model.id,
            "patient_id": model.patient_id,
            "bundle_id": model.bundle_id,
            "force_refresh": model.force_refresh,
            "status": model.status,
            "message": model.message,
            "created_at": model.created_at,
            "started_at": model.started_at,
            "completed_at": model.completed_at,
            "duration_seconds": model.duration_seconds,
            "summary": summary_obj,
            "error_message": model.error_message,
        }

    async def create_or_get_task(
        self,
        patient_id: str,
        bundle_id: Optional[str] = None,
        force_refresh: bool = False,
        session: Optional[AsyncSession] = None,
    ) -> Tuple[str, bool]:
        """Create a new background summarization task or return an ongoing one.

        Args:
            patient_id: Target patient ID.
            bundle_id: Optional FHIR bundle ID.
            force_refresh: Whether to bypass cache.
            session: Optional async DB session for persistence across workers.

        Returns:
            Tuple[task_id: str, is_new: bool]
        """
        with self._lock:
            existing_task_id = self._patient_latest_task.get(patient_id)
            if existing_task_id and existing_task_id in self._tasks:
                existing_task = self._tasks[existing_task_id]
                if existing_task["status"] in ("PENDING", "PROCESSING"):
                    return existing_task_id, False

        # If session provided, check DB for active task from other workers
        if session:
            stmt = (
                select(SummaryTaskModel)
                .where(
                    SummaryTaskModel.patient_id == patient_id,
                    SummaryTaskModel.status.in_(["PENDING", "PROCESSING"]),
                )
                .order_by(desc(SummaryTaskModel.created_at))
                .limit(1)
            )
            res = await session.execute(stmt)
            db_task = res.scalars().first()
            if db_task:
                task_dict = self._task_model_to_dict(db_task)
                with self._lock:
                    self._tasks[db_task.id] = task_dict
                    self._patient_latest_task[patient_id] = db_task.id
                return db_task.id, False

        task_id = f"sum-task-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        message = "AI clinical summary regeneration scheduled in background."

        task_record = {
            "task_id": task_id,
            "patient_id": patient_id,
            "bundle_id": bundle_id,
            "force_refresh": force_refresh,
            "status": "PENDING",
            "message": message,
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "summary": None,
            "error_message": None,
        }

        with self._lock:
            if len(self._tasks) >= self._max_history:
                oldest_key = next(iter(self._tasks))
                del self._tasks[oldest_key]

            self._tasks[task_id] = task_record
            self._patient_latest_task[patient_id] = task_id

        # Persist to database if session provided
        if session:
            db_model = SummaryTaskModel(
                id=task_id,
                patient_id=patient_id,
                bundle_id=bundle_id,
                force_refresh=force_refresh,
                status="PENDING",
                message=message,
                created_at=now,
            )
            session.add(db_model)
            await session.commit()

        return task_id, True

    async def get_task(
        self,
        task_id: str,
        session: Optional[AsyncSession] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve task record by task ID (checks memory, falls back to DB)."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                return dict(task)

        if session:
            stmt = select(SummaryTaskModel).where(SummaryTaskModel.id == task_id)
            res = await session.execute(stmt)
            model = res.scalars().first()
            if model:
                task_dict = self._task_model_to_dict(model)
                with self._lock:
                    self._tasks[task_id] = task_dict
                return task_dict

        return None

    async def get_latest_task_for_patient(
        self,
        patient_id: str,
        session: Optional[AsyncSession] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve latest task record for a given patient ID (checks memory, falls back to DB)."""
        with self._lock:
            task_id = self._patient_latest_task.get(patient_id)
            if task_id and task_id in self._tasks:
                return dict(self._tasks[task_id])

        if session:
            stmt = (
                select(SummaryTaskModel)
                .where(SummaryTaskModel.patient_id == patient_id)
                .order_by(desc(SummaryTaskModel.created_at))
                .limit(1)
            )
            res = await session.execute(stmt)
            model = res.scalars().first()
            if model:
                task_dict = self._task_model_to_dict(model)
                with self._lock:
                    self._tasks[model.id] = task_dict
                    self._patient_latest_task[patient_id] = model.id
                return task_dict

        return None

    async def mark_processing(
        self,
        task_id: str,
        session: Optional[AsyncSession] = None,
    ) -> None:
        """Mark task as actively processing in background worker."""
        now = datetime.now(timezone.utc)
        msg = "Inference in progress: synthesizing longitudinal records."
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "PROCESSING"
                self._tasks[task_id]["started_at"] = now
                self._tasks[task_id]["message"] = msg

        if session:
            stmt = select(SummaryTaskModel).where(SummaryTaskModel.id == task_id)
            res = await session.execute(stmt)
            model = res.scalars().first()
            if model:
                model.status = "PROCESSING"
                model.started_at = now
                model.message = msg
                await session.commit()

    async def mark_completed(
        self,
        task_id: str,
        summary: ClinicalSummaryResponse,
        latency_ms: float,
        session: Optional[AsyncSession] = None,
    ) -> None:
        """Mark task as successfully completed with generated summary."""
        now = datetime.now(timezone.utc)
        dur = round(latency_ms / 1000.0, 2)
        msg = "Clinical summary successfully synthesized and persisted."

        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "COMPLETED"
                self._tasks[task_id]["completed_at"] = now
                self._tasks[task_id]["duration_seconds"] = dur
                self._tasks[task_id]["summary"] = summary
                self._tasks[task_id]["message"] = msg

        if session:
            stmt = select(SummaryTaskModel).where(SummaryTaskModel.id == task_id)
            res = await session.execute(stmt)
            model = res.scalars().first()
            if model:
                model.status = "COMPLETED"
                model.completed_at = now
                model.duration_seconds = dur
                model.summary_json = summary.model_dump(mode="json")
                model.message = msg
                await session.commit()

    async def mark_failed(
        self,
        task_id: str,
        error_message: str,
        latency_ms: Optional[float] = None,
        session: Optional[AsyncSession] = None,
    ) -> None:
        """Mark task as failed with error details."""
        now = datetime.now(timezone.utc)
        dur = round(latency_ms / 1000.0, 2) if latency_ms is not None else None
        msg = f"Clinical summary generation failed: {error_message}"

        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "FAILED"
                self._tasks[task_id]["completed_at"] = now
                if dur is not None:
                    self._tasks[task_id]["duration_seconds"] = dur
                self._tasks[task_id]["error_message"] = error_message
                self._tasks[task_id]["message"] = msg

        if session:
            stmt = select(SummaryTaskModel).where(SummaryTaskModel.id == task_id)
            res = await session.execute(stmt)
            model = res.scalars().first()
            if model:
                model.status = "FAILED"
                model.completed_at = now
                if dur is not None:
                    model.duration_seconds = dur
                model.error_message = error_message
                model.message = msg
                await session.commit()


summary_task_manager = SummaryTaskManager()
