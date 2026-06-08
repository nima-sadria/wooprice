import io

import httpx
from openpyxl import load_workbook

from ..config import get_settings


def _auth() -> tuple[str, str]:
    s = get_settings()
    return (s.nextcloud_user, s.nextcloud_password)


def _webdav_url() -> str:
    s = get_settings()
    return s.nextcloud_url.rstrip("/") + s.nextcloud_file_path


async def download_xlsx() -> bytes:
    async with httpx.AsyncClient(auth=_auth(), follow_redirects=True) as client:
        resp = await client.get(_webdav_url(), timeout=30)
        resp.raise_for_status()
        return resp.content


def parse_price_list(xlsx_bytes: bytes) -> list[dict]:
    """Read rows A3:B1000. Returns [{product_id, new_price}] for valid rows only."""
    wb = load_workbook(filename=io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb.active
    items = []
    for row in ws.iter_rows(min_row=3, max_row=1000, min_col=1, max_col=2, values_only=True):
        pid_raw, price_raw = row
        if pid_raw is None:
            continue
        try:
            pid = int(pid_raw)
        except (ValueError, TypeError):
            continue
        if price_raw is None:
            items.append({"product_id": pid, "new_price": ""})
            continue
        try:
            price = float(price_raw)
        except (ValueError, TypeError):
            continue
        items.append({"product_id": pid, "new_price": f"{price:.2f}"})
    wb.close()
    return items


async def write_back_to_sheet(results: list[dict]) -> None:
    """Update columns E (status), F (sync time), G (error) by product_id."""
    result_map = {r["product_id"]: r for r in results}

    xlsx_bytes = await download_xlsx()
    wb = load_workbook(filename=io.BytesIO(xlsx_bytes), data_only=True)
    ws = wb.active

    for row_idx in range(3, 1001):
        cell_a = ws.cell(row=row_idx, column=1).value
        if cell_a is None:
            break
        try:
            pid = int(cell_a)
        except (ValueError, TypeError):
            continue
        if pid not in result_map:
            continue
        r = result_map[pid]
        ws.cell(row=row_idx, column=5).value = r.get("status", "")
        ws.cell(row=row_idx, column=6).value = r.get("synced_at", "")
        ws.cell(row=row_idx, column=7).value = r.get("error_message", "")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    async with httpx.AsyncClient(auth=_auth(), follow_redirects=True) as client:
        resp = await client.put(
            _webdav_url(),
            content=buf.read(),
            timeout=60,
            headers={
                "Content-Type": (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            },
        )
        resp.raise_for_status()
