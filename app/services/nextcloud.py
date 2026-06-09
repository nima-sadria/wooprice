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


def parse_price_list(xlsx_bytes: bytes) -> list[dict]:
    """
    Read sheet from row 3 onward.
    Column B = WooCommerce product ID (must be numeric, skip row if empty or non-numeric).
    Column D = BRSTPRICE / regular price (comma-separated string or number, empty/❌ means clear price).
    Returns [{product_id, new_price, row_color}].
    """
    wb = load_workbook(filename=io.BytesIO(xlsx_bytes), data_only=True)
    ws = wb.active
    items = []
    consecutive_empty = 0
    for row_idx in range(3, 1001):
        col_a = ws.cell(row=row_idx, column=1).value
        col_b = ws.cell(row=row_idx, column=2).value
        col_c = ws.cell(row=row_idx, column=3).value
        col_d = ws.cell(row=row_idx, column=4).value

        # Stop after 30 consecutive fully-empty rows
        if col_a is None and col_b is None and col_c is None and col_d is None:
            consecutive_empty += 1
            if consecutive_empty >= 30:
                break
            continue
        consecutive_empty = 0

        # Column B must be a valid positive integer product ID
        if col_b is None:
            continue
        try:
            pid = int(str(col_b).replace(",", "").strip())
        except (ValueError, TypeError):
            continue
        if pid <= 0:
            continue

        # Column D: BRSTPRICE (strip commas, convert to float string, or "" if empty/❌)
        if col_d is None or str(col_d).strip() in ("", "❌", "✕", "✗", "x", "X"):
            new_price = ""
        else:
            price_str = str(col_d).replace(",", "").strip()
            try:
                new_price = f"{float(price_str):.2f}"
            except (ValueError, TypeError):
                new_price = ""

        row_color = _extract_row_color(ws, row_idx)
        items.append({"product_id": pid, "new_price": new_price, "row_color": row_color})

    wb.close()
    return items


async def write_price_to_sheet(product_id: int, new_price: str) -> None:
    """Overwrite column D (BRSTPRICE) for the row whose column B matches product_id."""
    xlsx_bytes = await download_xlsx()
    wb = load_workbook(filename=io.BytesIO(xlsx_bytes))
    ws = wb.active

    consecutive_empty = 0
    for row_idx in range(3, 1001):
        col_a = ws.cell(row=row_idx, column=1).value
        col_b = ws.cell(row=row_idx, column=2).value
        col_c = ws.cell(row=row_idx, column=3).value
        col_d = ws.cell(row=row_idx, column=4).value
        if col_a is None and col_b is None and col_c is None and col_d is None:
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
                ws.cell(row=row_idx, column=4).value = float(new_price) if new_price else None
            except (ValueError, TypeError):
                ws.cell(row=row_idx, column=4).value = new_price or None
            break

    await _upload_wb(wb)


async def write_back_to_sheet(results: list[dict]) -> None:
    """Update columns E (status), F (sync time), G (error) by product_id (column B)."""
    result_map = {r["product_id"]: r for r in results}

    xlsx_bytes = await download_xlsx()
    wb = load_workbook(filename=io.BytesIO(xlsx_bytes))
    ws = wb.active

    consecutive_empty = 0
    for row_idx in range(3, 1001):
        col_a = ws.cell(row=row_idx, column=1).value
        col_b = ws.cell(row=row_idx, column=2).value
        col_c = ws.cell(row=row_idx, column=3).value
        col_d = ws.cell(row=row_idx, column=4).value
        if col_a is None and col_b is None and col_c is None and col_d is None:
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
