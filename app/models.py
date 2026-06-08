import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String
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
    sku = Column(String, nullable=True)
    old_price = Column(String, nullable=True)
    new_price = Column(String)
    sale_price = Column(String, nullable=True)
    stock_status = Column(String, nullable=True)
    stock_quantity = Column(Integer, nullable=True)
    categories = Column(String, nullable=True)  # JSON: [{"id":1,"name":"..."}]
    status = Column(SAEnum(ItemStatus), default=ItemStatus.pending)
    error_message = Column(String, nullable=True)
    synced_at = Column(DateTime, nullable=True)

    job = relationship("SyncJob", back_populates="items")


class AlarmThreshold(Base):
    """Price-change alarm thresholds. category_id=None means global default."""
    __tablename__ = "alarm_thresholds"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, nullable=True, index=True)  # None = global
    threshold_percent = Column(Float, nullable=False)


class AuditLog(Base):
    """Records every login, fetch preview, and apply action with user + timestamp."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)  # "login" | "fetch" | "apply"
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ip_address = Column(String, nullable=True)
    job_id = Column(Integer, nullable=True)
