import io
import time

import httpx
from openpyxl import load_workbook

from ..config import get_settings


def _auth() -> tuple[str, str]:
    s = get_settings()
    return (s.nextcloud_user, s.nextcloud_password)


def _webdav_url() -> str:
    s = get_settings()
    return s.nextcloud_url.rstrip("/") + s.nextcloud_file_path


# Short read-cache for preview flow; invalidated after every upload
_xlsx_cache: dict = {"data": None, "ts": 0.0}
_XLSX_CACHE_TTL = 60  # seconds


async def download_xlsx(force: bool = False) -> bytes:
    if (
        not force
        and _xlsx_cache["data"] is not None
        and time.time() - _xlsx_cache["ts"] < _XLSX_CACHE_TTL
    ):
        return _xlsx_cache["data"]
    async with httpx.AsyncClient(auth=_auth(), follow_redirects=True) as client:
        resp = await client.get(_webdav_url(), timeout=httpx.Timeout(10.0, read=60.0))
        resp.raise_for_status()
        data = resp.content
    _xlsx_cache["data"] = data
    _xlsx_cache["ts"] = time.time()
    return data


def _extract_row_color(ws, row_idx: int) -> str | None:
    """Return #RRGGBB from column A fill, or None if no significant color."""
    try:
        fill = ws.cell(row=row_idx, column=1).fill
        if fill and fill.fill_type == "solid":
            fg = fill.fgColor
            if fg and fg.type == "rgb":
                rgb = fg.rgb  # ARGB: 'FF4472C4'
                if len(rgb) == 8 and rgb[:2] == "FF":
                    hex6 = rgb[2:]
                    if hex6 not in ("000000", "FFFFFF", "ffffff"):
                        return "#" + hex6
    except Exception:
        pass
    return None


def _parse_sheet_rows(ws) -> list[dict]:
    """Parse one worksheet using the standard column mapping (B=ID, C=price, A=color)."""
    items = []
    consecutive_empty = 0
    for row_idx in range(3, 1001):
        col_a = ws.cell(row=row_idx, column=1).value
        col_b = ws.cell(row=row_idx, column=2).value
        col_c = ws.cell(row=row_idx, column=3).value

        if col_a is None and col_b is None and col_c is None:
            consecutive_empty += 1
            if consecutive_empty >= 30:
                break
            continue
        consecutive_empty = 0

        if col_b is None:
            continue
        try:
            pid = int(str(col_b).replace(",", "").strip())
        except (ValueError, TypeError):
            continue
        if pid <= 0:
            continue

        if col_c is None or str(col_c).strip() == "":
            new_price = ""
        else:
            price_str = str(col_c).replace(",", "").strip()
            try:
                new_price = f"{float(price_str):.2f}"
            except (ValueError, TypeError):
                new_price = ""

        row_color = _extract_row_color(ws, row_idx)
        sheet_name = str(col_a).strip() if col_a is not None else ""
        items.append({"product_id": pid, "new_price": new_price, "row_color": row_color, "sheet_name": sheet_name})
    return items


def parse_price_list(xlsx_bytes: bytes) -> tuple[list[dict], list[dict]]:
    """
    Read ALL sheets from row 3 onward using the same column mapping.
    Column B = WooCommerce product ID, Column C = regular price, Column A = row color/name.
    If the same product ID appears in multiple sheets, the last sheet wins.
    Returns (items, duplicate_warnings).
    Each warning: {product_id, prev_sheet, final_sheet, prev_price, final_price}.
    """
    wb = load_workbook(filename=io.BytesIO(xlsx_bytes), data_only=True)
    seen: dict[int, dict] = {}
    duplicates: list[dict] = []

    for ws in wb.worksheets:
        tab = ws.title
        for item in _parse_sheet_rows(ws):
            pid = item["product_id"]
            if pid in seen:
                duplicates.append({
                    "product_id": pid,
                    "prev_sheet": seen[pid].get("_tab", ""),
                    "final_sheet": tab,
                    "prev_price": seen[pid]["new_price"],
                    "final_price": item["new_price"],
                })
            item["_tab"] = tab
            seen[pid] = item

    wb.close()
    items = [{k: v for k, v in i.items() if k != "_tab"} for i in seen.values()]
    return items, duplicates


async def write_price_to_sheet(product_id: int, new_price: str) -> None:
    """Overwrite column C for the row whose column B matches product_id."""
    xlsx_bytes = await download_xlsx(force=True)
    wb = load_workbook(filename=io.BytesIO(xlsx_bytes))
    ws = wb.active

    consecutive_empty = 0
    for row_idx in range(3, 1001):
        col_a = ws.cell(row=row_idx, column=1).value
        col_b = ws.cell(row=row_idx, column=2).value
        col_c = ws.cell(row=row_idx, column=3).value
        if col_a is None and col_b is None and col_c is None:
            consecutive_empty += 1
            if consecutive_empty >= 30:
                break
            continue
        consecutive_empty = 0
        if col_b is None:
            continue
        try:
            pid = int(str(col_b).replace(",", "").strip())
        except (ValueError, TypeError):
            continue
        if pid == product_id:
            try:
                ws.cell(row=row_idx, column=3).value = float(new_price) if new_price else None
            except (ValueError, TypeError):
                ws.cell(row=row_idx, column=3).value = new_price or None
            break

    await _upload_wb(wb)


async def write_back_to_sheet(results: list[dict]) -> None:
    """Update columns E (status), F (sync time), G (error) by product_id (column B)."""
    result_map = {r["product_id"]: r for r in results}

    xlsx_bytes = await download_xlsx(force=True)
    wb = load_workbook(filename=io.BytesIO(xlsx_bytes))
    ws = wb.active

    consecutive_empty = 0
    for row_idx in range(3, 1001):
        col_a = ws.cell(row=row_idx, column=1).value
        col_b = ws.cell(row=row_idx, column=2).value
        col_c = ws.cell(row=row_idx, column=3).value
        if col_a is None and col_b is None and col_c is None:
            consecutive_empty += 1
            if consecutive_empty >= 30:
                break
            continue
        consecutive_empty = 0
        if col_b is None:
            continue
        try:
            pid = int(str(col_b).replace(",", "").strip())
        except (ValueError, TypeError):
            continue
        if pid not in result_map:
            continue
        r = result_map[pid]
        ws.cell(row=row_idx, column=5).value = r.get("status", "")
        ws.cell(row=row_idx, column=6).value = r.get("synced_at", "")
        ws.cell(row=row_idx, column=7).value = r.get("error_message", "")

    await _upload_wb(wb)


async def _upload_wb(wb) -> None:
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
    _xlsx_cache["data"] = None  # invalidate so next read fetches the just-uploaded file
