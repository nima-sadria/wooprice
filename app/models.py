import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum as SAEnum, Float, ForeignKey, Index, Integer, String, Text
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
    __table_args__ = (
        Index("ix_sync_jobs_status_created_at", "status", "created_at"),
    )

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
    dry_run_scope = Column(Text, nullable=True)         # JSON: [product_id, ...] or null for job-wide

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
    # Phase C — validation + precise change detection
    validation_level = Column(String, nullable=True)      # info | warning | error | critical
    wc_price_at_preview = Column(String, nullable=True)   # WC price at preview time (from cache)
    wc_stock_at_preview = Column(String, nullable=True)   # WC stock_status at preview time

    job = relationship("SyncJob", back_populates="items")


class AlarmThreshold(Base):
    """Price-change alarm thresholds. category_id=None means global default."""
    __tablename__ = "alarm_thresholds"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, nullable=True, index=True)  # None = global
    threshold_percent = Column(Float, nullable=False)  # warning threshold (%)
    critical_threshold_percent = Column(Float, nullable=True)  # optional blocking threshold (%)
    block_enabled = Column(Boolean, nullable=False, default=False)  # gate for critical_threshold_percent


class ProductCache(Base):
    """Persistent local cache of WooCommerce products and variations."""
    __tablename__ = "products_cache"
    __table_args__ = (
        Index("ix_products_cache_stock_status", "stock_status"),
        Index("ix_products_cache_last_synced_at", "last_synced_at"),
    )

    wc_id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, default=0, index=True)
    product_type = Column(String, default="simple")   # simple | variable | variation
    sku = Column(String, nullable=True, index=True)
    name = Column(String, nullable=True)              # WooCommerce name (reference only)
    status = Column(String, nullable=True)
    stock_status = Column(String, nullable=True)
    stock_quantity = Column(Integer, nullable=True)
    manage_stock = Column(String, nullable=True)     # "true" | "false" | "parent" | None
    regular_price = Column(String, nullable=True)
    sale_price = Column(String, nullable=True)
    final_price = Column(String, nullable=True)       # effective display price
    categories = Column(Text, nullable=True)          # JSON: [{"id":1,"name":"..."}]
    brand_id = Column(Integer, nullable=True, index=True)    # WC product_brand term id; NULL = unassigned
    brand_name = Column(String, nullable=True)                # denormalized for display; NULL = unassigned
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


class ChangeHistory(Base):
    """Phase C — immutable record of every WooCommerce price/stock change, enabling rollback.
    One row is written immediately BEFORE each WC update, capturing the prior state."""
    __tablename__ = "change_history"
    __table_args__ = (
        Index("ix_change_history_source_changed_at", "source", "changed_at"),
    )

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, nullable=False, index=True)
    parent_id = Column(Integer, default=0, nullable=True)
    old_price = Column(String, nullable=True)
    new_price = Column(String, nullable=True)
    old_stock_status = Column(String, nullable=True)
    new_stock_status = Column(String, nullable=True)
    old_manage_stock = Column(Boolean, nullable=True)
    new_manage_stock = Column(Boolean, nullable=True)
    old_stock_quantity = Column(Integer, nullable=True)
    new_stock_quantity = Column(Integer, nullable=True)
    changed_at = Column(DateTime, default=datetime.utcnow, index=True)
    username = Column(String, nullable=True)
    job_id = Column(Integer, nullable=True, index=True)
    source = Column(String, nullable=True)              # apply | direct_edit | rollback | emergency | undo
    rollback_of_id = Column(Integer, ForeignKey("change_history.id"), nullable=True)
    batch_id = Column(Integer, nullable=True, index=True)  # links emergency batch apply rows
    brand_id = Column(Integer, nullable=True)           # brand active at change time (for velocity metrics)
    price_delta_pct = Column(Float, nullable=True)      # pre-computed (new-old)/old*100


class EmergencyBatch(Base):
    """An emergency price update batch created by a user outside the normal sheet sync flow."""
    __tablename__ = "emergency_batches"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, nullable=False)
    operation = Column(String, nullable=False)   # pct_increase | pct_decrease | fixed_increase | fixed_decrease
    value = Column(Float, nullable=False)        # percent (0–100] or fixed amount (>0)
    status = Column(String, nullable=False, default="pending")
    # batch statuses: pending | applying | applied | partially_failed | failed | needs_reconcile | cancelled
    applied_at = Column(DateTime, nullable=True)
    filter_snapshot = Column(Text, nullable=True)  # JSON: filters used to select products

    items = relationship("EmergencyItem", back_populates="batch", cascade="all, delete-orphan")


class EmergencyItem(Base):
    """One product within an EmergencyBatch: holds the computed new price before/after apply."""
    __tablename__ = "emergency_items"
    __table_args__ = (
        Index("ix_emergency_items_batch_id", "batch_id"),
        Index("ix_emergency_items_product_id", "product_id"),
    )

    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("emergency_batches.id"), nullable=False)
    product_id = Column(Integer, nullable=False)
    sku = Column(String, nullable=True)
    product_name = Column(String, nullable=True)
    old_price = Column(String, nullable=True)  # price from cache at preview time (baseline for stale check)
    new_price = Column(String, nullable=True)  # computed and rounded new price
    status = Column(String, nullable=False, default="pending")
    # item statuses: pending | applying | wc_succeeded | applied | failed | skipped | stale | needs_reconcile
    wc_success_at = Column(DateTime, nullable=True)  # set immediately after WC write succeeds, before DB finalization
    applied_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)

    batch = relationship("EmergencyBatch", back_populates="items")


class AppSetting(Base):
    """Key-value store for application-level settings (e.g. maintenance mode)."""
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)   # JSON-encoded value
    updated_at = Column(DateTime, nullable=True)
    updated_by = Column(String, nullable=True)


class ChangeTracking(Base):
    """Phase C — field-level audit of every detected value drift, from either the sheet
    (preview) or a WooCommerce fetch. Distinct from ChangeHistory (which is rollback-oriented)."""
    __tablename__ = "change_tracking"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, nullable=False, index=True)
    detected_at = Column(DateTime, default=datetime.utcnow, index=True)
    field_name = Column(String, nullable=True)          # price | stock_status | stock_quantity
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    source = Column(String, nullable=True)              # sheet | wc_fetch
    job_id = Column(Integer, nullable=True, index=True)


class DailyMetrics(Base):
    """Phase C — analytics foundation. One row per calendar day (UTC), upserted as events occur."""
    __tablename__ = "daily_metrics"

    id = Column(Integer, primary_key=True)
    date = Column(String, nullable=False, unique=True, index=True)  # YYYY-MM-DD
    total_products = Column(Integer, default=0)
    changed_products = Column(Integer, default=0)
    updated_products = Column(Integer, default=0)
    failed_products = Column(Integer, default=0)
    validation_errors = Column(Integer, default=0)
    apply_jobs = Column(Integer, default=0)
    rollback_jobs = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
