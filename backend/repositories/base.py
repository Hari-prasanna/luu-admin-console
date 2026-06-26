"""Base repository class with common CRUD operations.

All repositories inherit from BaseRepository to ensure consistent:
- Query patterns
- Error handling
- Pagination
- Type safety

Usage:
    class MetricRepository(BaseRepository[MetricHistory]):
        def __init__(self, db: AsyncSession):
            super().__init__(db, MetricHistory)

        async def get_by_metric_and_date_range(self, metric_key, start, end):
            # Specific query logic
            result = await self.db.execute(
                select(self.model).where(
                    and_(
                        self.model.metric_key == metric_key,
                        self.model.timestamp.between(start, end),
                    )
                )
            )
            return result.scalars().all()
"""

from typing import TypeVar, Generic, Optional, List, Dict, Any
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.exceptions import NotFoundError, DatabaseError

T = TypeVar('T')


class BaseRepository(Generic[T]):
    """Generic repository base class with CRUD operations."""

    def __init__(self, db: AsyncSession, model: type[T]):
        """Initialize repository.

        Args:
            db: AsyncSession for database operations
            model: SQLAlchemy model class
        """
        self.db = db
        self.model = model

    async def create(self, **kwargs) -> T:
        """Create and return entity.

        Args:
            **kwargs: Entity fields

        Returns:
            Created entity instance

        Raises:
            DatabaseError: If creation fails
        """
        try:
            entity = self.model(**kwargs)
            self.db.add(entity)
            await self.db.flush()
            return entity
        except Exception as e:
            raise DatabaseError(
                f"Failed to create {self.model.__name__}"
            ) from e

    async def get_by_id(self, id: Any) -> T:
        """Get entity by ID.

        Args:
            id: Entity ID

        Returns:
            Entity instance

        Raises:
            NotFoundError: If entity not found
        """
        result = await self.db.execute(
            select(self.model).where(self.model.id == id)
        )
        entity = result.scalar_one_or_none()

        if not entity:
            raise NotFoundError(
                f"{self.model.__name__} with id {id} not found"
            )

        return entity

    async def list(
        self,
        limit: int = 50,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[T], int]:
        """List with pagination and optional filters.

        Args:
            limit: Max number of items (1-1000)
            offset: Number of items to skip
            filters: Dict of field:value for filtering

        Returns:
            Tuple of (items list, total count)
        """
        # Build query with filters
        query = select(self.model)

        if filters:
            conditions = [
                getattr(self.model, k) == v
                for k, v in filters.items()
                if hasattr(self.model, k)
            ]
            if conditions:
                query = query.where(and_(*conditions))

        # Get total count
        count_query = select(func.count()).select_from(self.model)
        if filters:
            conditions = [
                getattr(self.model, k) == v
                for k, v in filters.items()
                if hasattr(self.model, k)
            ]
            if conditions:
                count_query = count_query.where(and_(*conditions))

        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Get paginated results
        result = await self.db.execute(
            query.limit(limit).offset(offset)
        )
        items = result.scalars().all()

        return items, total

    async def update(self, id: Any, **kwargs) -> T:
        """Update entity.

        Args:
            id: Entity ID
            **kwargs: Fields to update

        Returns:
            Updated entity

        Raises:
            NotFoundError: If entity not found
            DatabaseError: If update fails
        """
        try:
            entity = await self.get_by_id(id)

            for key, value in kwargs.items():
                if hasattr(entity, key):
                    setattr(entity, key, value)

            await self.db.flush()
            return entity

        except NotFoundError:
            raise
        except Exception as e:
            raise DatabaseError(
                f"Failed to update {self.model.__name__}"
            ) from e

    async def delete(self, id: Any) -> bool:
        """Delete entity.

        Args:
            id: Entity ID

        Returns:
            True if deleted

        Raises:
            NotFoundError: If entity not found
            DatabaseError: If deletion fails
        """
        try:
            entity = await self.get_by_id(id)
            await self.db.delete(entity)
            await self.db.flush()
            return True

        except NotFoundError:
            raise
        except Exception as e:
            raise DatabaseError(
                f"Failed to delete {self.model.__name__}"
            ) from e

    async def exists(self, **filters) -> bool:
        """Check if entity with filters exists.

        Args:
            **filters: Field:value filters

        Returns:
            True if entity exists
        """
        query = select(func.count()).select_from(self.model)

        if filters:
            conditions = [
                getattr(self.model, k) == v
                for k, v in filters.items()
                if hasattr(self.model, k)
            ]
            if conditions:
                query = query.where(and_(*conditions))

        result = await self.db.execute(query)
        count = result.scalar() or 0
        return count > 0

    async def count(self, **filters) -> int:
        """Count entities matching filters.

        Args:
            **filters: Field:value filters

        Returns:
            Count of matching entities
        """
        query = select(func.count()).select_from(self.model)

        if filters:
            conditions = [
                getattr(self.model, k) == v
                for k, v in filters.items()
                if hasattr(self.model, k)
            ]
            if conditions:
                query = query.where(and_(*conditions))

        result = await self.db.execute(query)
        return result.scalar() or 0
