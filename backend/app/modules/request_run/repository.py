import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_repository import BaseRepository
from app.modules.request_run.model import RequestRun, RequestRunStatus
from app.modules.conversation.model import Message, MessageRole


class RequestRunRepository(BaseRepository[RequestRun]):
    def __init__(self, db: AsyncSession):
        super().__init__(RequestRun, db)

    async def get_owned(
        self, request_id: uuid.UUID, user_id: uuid.UUID
    ) -> RequestRun | None:
        statement = select(RequestRun).where(
            RequestRun.id == request_id,
            RequestRun.user_id == user_id,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def get_by_user_idempotency(
        self, user_id: uuid.UUID, idempotency_key: str
    ) -> RequestRun | None:
        statement = select(RequestRun).where(
            RequestRun.user_id == user_id,
            RequestRun.idempotency_key == idempotency_key,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def get_running_for_conversation(
        self, conversation_id: uuid.UUID
    ) -> RequestRun | None:
        statement = select(RequestRun).where(
            RequestRun.conversation_id == conversation_id,
            RequestRun.status == RequestRunStatus.RUNNING,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def get_message(
        self,
        request_id: uuid.UUID,
        role: MessageRole,
    ) -> Message | None:
        statement = select(Message).where(
            Message.request_id == request_id,
            Message.role == role,
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def transition_owned_from_running(
        self,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        status: RequestRunStatus,
        finished_at: datetime,
        error_code: str | None,
    ) -> bool:
        statement = (
            update(RequestRun)
            .where(
                RequestRun.id == request_id,
                RequestRun.user_id == user_id,
                RequestRun.status == RequestRunStatus.RUNNING,
            )
            .values(
                status=status,
                finished_at=finished_at,
                error_code=error_code,
            )
            .returning(RequestRun.id)
        )
        transitioned_id = (await self.db.execute(statement)).scalar_one_or_none()
        return transitioned_id is not None

    async def transition_from_running(
        self,
        request_id: uuid.UUID,
        *,
        status: RequestRunStatus,
        finished_at: datetime,
        error_code: str | None,
    ) -> bool:
        statement = (
            update(RequestRun)
            .where(
                RequestRun.id == request_id,
                RequestRun.status == RequestRunStatus.RUNNING,
            )
            .values(
                status=status,
                finished_at=finished_at,
                error_code=error_code,
            )
            .returning(RequestRun.id)
        )
        transitioned_id = (await self.db.execute(statement)).scalar_one_or_none()
        return transitioned_id is not None
