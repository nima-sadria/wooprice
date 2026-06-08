import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base


class JobStatus(str, enum.Enum):
    preview = "preview"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ItemStatus(str, enum.Enum):
    pending = "pending"
    updated = "updated"
    failed = "failed"
    skipped = "skipped"


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    status = Column(SAEnum(JobStatus), default=JobStatus.preview)
    total_count = Column(Integer, default=0)
    updated_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)

    items = relationship("SyncItem", back_populates="job", cascade="all, delete-orphan")


class SyncItem(Base):
    __tablename__ = "sync_items"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("sync_jobs.id"))
    product_id = Column(Integer, index=True)
    parent_id = Column(Integer, default=0, nullable=True)
    product_name = Column(String, nullable=True)
    old_price = Column(String, nullable=True)
    new_price = Column(String)
    status = Column(SAEnum(ItemStatus), default=ItemStatus.pending)
    error_message = Column(String, nullable=True)
    synced_at = Column(DateTime, nullable=True)

    job = relationship("SyncJob", back_populates="items")
