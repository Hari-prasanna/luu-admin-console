"""
Feedback endpoint: stores user-submitted feedback to PostgreSQL.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db_session as get_session
from backend.db_models import UserFeedback
from backend.api.v1.routes.auth import get_authenticated_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackCreate(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    category: Optional[str] = Field(None, description="general | bug | feature | ui_ux")
    rating: Optional[int] = Field(None, ge=1, le=5)
    page_context: Optional[str] = Field(None, max_length=200)


class FeedbackResponse(BaseModel):
    id: int
    submitted: bool


@router.post("", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(
    request: FeedbackCreate,
    current_user: dict = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_session),
):
    """Submit user feedback. Requires any authenticated user."""
    feedback = UserFeedback(
        username=current_user.get("username", "unknown"),
        user_id=current_user.get("user_id"),
        category=request.category or "general",
        rating=request.rating,
        message=request.message.strip(),
        page_context=request.page_context,
        submitted_at=datetime.now(timezone.utc),
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(feedback)
    logger.info(
        "feedback_submitted",
        extra={"user": current_user.get("username"), "category": feedback.category},
    )
    return FeedbackResponse(id=feedback.id, submitted=True)


@router.get("", status_code=200)
async def list_feedback(
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_session),
):
    """List all feedback entries. Requires admin role."""
    from fastapi import HTTPException
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    from sqlalchemy import select
    stmt = (
        select(UserFeedback)
        .order_by(UserFeedback.submitted_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return {
        "status": "ok",
        "total": len(rows),
        "feedback": [
            {
                "id": r.id,
                "username": r.username,
                "category": r.category,
                "rating": r.rating,
                "message": r.message,
                "page_context": r.page_context,
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            }
            for r in rows
        ],
    }
