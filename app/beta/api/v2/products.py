"""WooPrice Beta — /api/v2/products router.

Read-only product inspection endpoints. Exposes A2 product data.

Implementation begins in B5.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/products", tags=["products"])

# Endpoints implemented in B5.
