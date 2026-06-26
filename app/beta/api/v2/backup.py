"""WooPrice Beta — /api/v2/backup router.

Backup create/list/restore endpoints. Admin permission required.

Implementation begins in B13.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/backup", tags=["backup"])

# Endpoints implemented in B13.
