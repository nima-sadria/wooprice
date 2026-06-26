"""A2.9 AI Foundation — AdvisoryRepository.

Isolation boundary:
- Never imported by Rule Engine, Safety Engine, Change Set Engine, Dry Run Engine,
  Execution Engine, or Scheduling Engine.
- Writes only to a2_advisory_sessions and a2_advisory_insights tables.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .models import AdvisoryInsight, AdvisorySession


class SessionNotFoundError(Exception):
    pass


class AdvisoryRepository:
    """Persistence layer for A2.9 advisory sessions and insights."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Session operations ─────────────────────────────────────────────────────

    def create_session(
        self,
        *,
        category: str,
        subject_type: str,
        subject_id: str,
        model_version: str,
        prompt_text: Optional[str] = None,
    ) -> AdvisorySession:
        now = datetime.now(tz=timezone.utc)
        session = AdvisorySession(
            category=category,
            subject_type=subject_type,
            subject_id=subject_id,
            model_version=model_version,
            prompt_text=prompt_text,
            created_at=now,
        )
        self._db.add(session)
        self._db.flush()
        return session

    def get_session(self, session_id: str) -> AdvisorySession:
        s = self._db.query(AdvisorySession).filter(AdvisorySession.id == session_id).first()
        if s is None:
            raise SessionNotFoundError(f"AdvisorySession {session_id!r} not found")
        return s

    def archive_session(self, session_id: str) -> AdvisorySession:
        s = self.get_session(session_id)
        s.is_archived = True
        s.closed_at = datetime.now(tz=timezone.utc)
        self._db.flush()
        return s

    # ── Insight operations ─────────────────────────────────────────────────────

    def store_insight(
        self,
        *,
        session_id: str,
        category: str,
        severity: str,
        confidence: float,
        summary: str,
        explanation: str,
        evidence: str,
        related_object_type: Optional[str] = None,
        related_object_id: Optional[str] = None,
        recommendation_trace: Optional[str] = None,
    ) -> AdvisoryInsight:
        insight = AdvisoryInsight(
            session_id=session_id,
            category=category,
            severity=severity,
            confidence=confidence,
            summary=summary,
            explanation=explanation,
            evidence=evidence,
            related_object_type=related_object_type,
            related_object_id=related_object_id,
            recommendation_trace=recommendation_trace,
            generated_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(insight)
        self._db.flush()
        return insight

    def list_insights(
        self,
        *,
        session_id: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[AdvisoryInsight]:
        q = self._db.query(AdvisoryInsight)
        if session_id is not None:
            q = q.filter(AdvisoryInsight.session_id == session_id)
        if category is not None:
            q = q.filter(AdvisoryInsight.category == category)
        return q.order_by(AdvisoryInsight.generated_at).all()
