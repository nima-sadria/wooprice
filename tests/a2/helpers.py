"""Shared test helpers for A2 tests."""
import io

from openpyxl import Workbook


def _make_xlsx(rows: list[tuple]) -> bytes:
    """
    Build a minimal WooPrice-format XLSX in memory.

    rows: list of (col_a, col_b, col_c) tuples, inserted starting at row 3.
    Rows 1–2 are left as header placeholders.
    """
    wb = Workbook()
    ws = wb.active
    ws.cell(row=1, column=1).value = "Label"
    ws.cell(row=1, column=2).value = "Product ID"
    ws.cell(row=1, column=3).value = "Price"
    for i, (a, b, c) in enumerate(rows, start=3):
        ws.cell(row=i, column=1).value = a
        ws.cell(row=i, column=2).value = b
        ws.cell(row=i, column=3).value = c
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
