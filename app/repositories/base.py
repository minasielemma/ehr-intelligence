"""Base repository pattern for asynchronous SQLite data access using SQLAlchemy 2.0."""

from typing import Generic, Optional, Type, TypeVar
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Base repository class providing session binding and common operations."""

    def __init__(self, session: AsyncSession, model_cls: Type[T]) -> None:
        self.session = session
        self.model_cls = model_cls

    async def get_by_id(self, record_id: str) -> Optional[T]:
        """Fetch entity by primary key."""
        return await self.session.get(self.model_cls, record_id)
