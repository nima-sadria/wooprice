import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String, Text
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
    sheet_hash = Column(String, nullable=True)
    # Phase B — change detection summary counts
    changed_count = Column(Integer, nullable=True)
    unchanged_count = Column(Integer, nullable=True)
    new_count = Column(Integer, nullable=True)
    invalid_count = Column(Integer, nullable=True)
    price_changed_count = Column(Integer, nullable=True)
    stock_changed_count = Column(Integer, nullable=True)
    missing_image_count = Column(Integer, nullable=True)
    # Phase B — dry run
    dry_run_summary = Column(Text, nullable=True)       # JSON blob
    dry_run_status = Column(String, nullable=True)      # passed | warnings | blocked
    dry_run_completed_at = Column(DateTime, nullable=True)

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
    row_color = Column(String, nullable=True)
    status = Column(SAEnum(ItemStatus), default=ItemStatus.pending)
    # Phase B — granular change flags
    change_status = Column(String, nullable=True)       # changed | unchanged | new | missing_from_wc_cache | invalid
    price_changed = Column(Integer, nullable=True)      # 0/1
    stock_changed = Column(Integer, nullable=True)      # 0/1
    name_changed = Column(Integer, nullable=True)       # 0/1 (always 0; sheet has no name column)
    category_changed = Column(Integer, nullable=True)   # 0/1 (always 0; sheet has no category column)
    missing_cost = Column(Integer, nullable=True)       # 0/1
    missing_image = Column(Integer, nullable=True)      # 0/1
    error_message = Column(String, nullable=True)
    synced_at = Column(DateTime, nullable=True)
    last_price_updated = Column(DateTime, nullable=True)
    wc_date_modified = Column(DateTime, nullable=True)

    job = relationship("SyncJob", back_populates="items")


class AlarmThreshold(Base):
    """Price-change alarm thresholds. category_id=None means global default."""
    __tablename__ = "alarm_thresholds"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, nullable=True, index=True)  # None = global
    threshold_percent = Column(Float, nullable=False)


class ProductCache(Base):
    """Persistent local cache of WooCommerce products and variations."""
    __tablename__ = "products_cache"

    wc_id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, default=0, index=True)
    product_type = Column(String, default="simple")   # simple | variable | variation
    sku = Column(String, nullable=True, index=True)
    name = Column(String, nullable=True)              # WooCommerce name (reference only)
    status = Column(String, nullable=True)
    stock_status = Column(String, nullable=True)
    stock_quantity = Column(Integer, nullable=True)
    regular_price = Column(String, nullable=True)
    sale_price = Column(String, nullable=True)
    final_price = Column(String, nullable=True)       # effective display price
    categories = Column(Text, nullable=True)          # JSON: [{"id":1,"name":"..."}]
    date_modified_gmt = Column(String, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    cache_version = Column(Integer, default=1)
    image_url = Column(String, nullable=True)
    image_source = Column(String, nullable=True)    # simple | variation | parent | none
    image_last_synced_at = Column(DateTime, nullable=True)


class AppUser(Base):
    """DB-backed access list. Super-admin users (SUPER_ADMIN_USERS env) bypass this table."""
    __tablename__ = "app_users"

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=True)
    email = Column(String, nullable=True, unique=True, index=True)  # lowercase; used for email-based login
    is_active = Column(Boolean, nullable=False, default=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    permission_version = Column(Integer, nullable=False, default=1)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
    # Granular permissions — defaults mirror safe non-admin baseline
    can_access_site   = Column(Boolean, nullable=False, default=True)
    can_fetch         = Column(Boolean, nullable=False, default=True)
    can_apply         = Column(Boolean, nullable=False, default=True)
    can_edit_price    = Column(Boolean, nullable=False, default=True)
    can_edit_stock    = Column(Boolean, nullable=False, default=True)
    can_view_logs     = Column(Boolean, nullable=False, default=False)
    can_view_settings = Column(Boolean, nullable=False, default=False)


class AuditLog(Base):
    """Records every login, fetch preview, apply, and direct product update."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)  # "login"|"fetch"|"apply"|"update_price"|"update_stock"
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    ip_address = Column(String, nullable=True)
    job_id = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)  # JSON: product_id, old/new values, parent_id
