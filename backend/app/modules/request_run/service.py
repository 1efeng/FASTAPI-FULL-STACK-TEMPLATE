import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.request_run.model import RequestRun
from app.modules.request_run.repository import RequestRunRepository


class RequestRunService:
    def __init__(self, db: AsyncSession):
        self.repo = RequestRunRepository(db)

    async def get_request_status(
        self, request_id: uuid.UUID, user_id: uuid.UUID
    ) -> RequestRun:
        request_run = await self.repo.get_owned(request_id, user_id)
        if request_run is None:
            raise HTTPException(status_code=404, detail="Request not found")
        return request_run
