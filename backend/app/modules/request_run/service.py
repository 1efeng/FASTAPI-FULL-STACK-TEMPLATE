import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.execution import get_execution_supervisor
from app.modules.chat.runtime import ChatRuntime
from app.modules.request_run.model import RequestRun, RequestRunStatus
from app.modules.request_run.repository import RequestRunRepository


class RequestRunService:
    def __init__(
        self,
        db: AsyncSession,
        runtime: ChatRuntime | None = None,
    ):
        self.db = db
        self.runtime = runtime
        self.repo = RequestRunRepository(db)

    async def get_request_status(
        self, request_id: uuid.UUID, user_id: uuid.UUID
    ) -> RequestRun:
        request_run = await self.repo.get_owned(request_id, user_id)
        if request_run is None:
            raise HTTPException(status_code=404, detail="Request not found")
        return request_run

    async def cancel_request(
        self, request_id: uuid.UUID, user_id: uuid.UUID
    ) -> RequestRun:
        request_run = await self.get_request_status(request_id, user_id)
        if request_run.status is not RequestRunStatus.RUNNING:
            return request_run

        transitioned = await self.repo.transition_owned_from_running(
            request_id,
            user_id,
            status=RequestRunStatus.CANCELLED,
            finished_at=datetime.now(UTC),
            error_code=None,
        )
        if transitioned:
            await self.db.commit()
            if self.runtime is not None:
                await self.runtime.signal_cancel(request_id)
            get_execution_supervisor().request_cancel(request_id)
        else:
            await self.db.rollback()

        current = await self.repo.get_owned(request_id, user_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Request not found")
        return current
