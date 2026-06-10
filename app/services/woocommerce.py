import asyncio
import time
from datetime import datetime, timezone

import httpx

from ..config import get_settings


def _auth() -> tuple[str, str]:
    s = get_settings()
    return (s.wc_key, s.wc_secret)


def _base() -> str:
    return get_settings().wc_url.rstrip("/") + "/wp-json/wc/v3"


_PRODUCT_FIELDS = "id,name,regular_price,sale_price,price,sku,stock_status,stock_quantity,categories,date_modified_gmt"

# In-memory product cache: {product_id: (data_dict, timestamp)}
_product_cache: dict[int, tuple[dict, float]] = {}
_cache_last_populated: float = 0.0  # epoch when fetch_product_prices last completed


def _cache_ttl() -> float:
    from ..config import get_settings
    hours = get_settings().wc_cache_ttl_hours
    return hours * 3600 if hours > 0 else float("inf")


def _cache_get(pid: int) -> dict | None:
    entry = _product_cache.get(pid)
    if entry and time.time() - entry[1] < _cache_ttl():
        return entry[0]
    return None


def _cache_set(pid: int, data: dict) -> None:
    _product_cache[pid] = (data, time.time())


def clear_product_cache() -> None:
    global _cache_last_populated
    _product_cache.clear()
    _cache_last_populated = 0.0


def get_cache_info() -> dict:
    now = time.time()
    age = (now - _cache_last_populated) if _cache_last_populated else None
    return {
        "size": len(_product_cache),
        "last_populated_ts": _cache_last_populated or None,
        "age_seconds": age,
    }


def _parse_product(p: dict) -> dict:
    return {
        "name": p.get("name", ""),
        "price": p.get("regular_price") or p.get("price") or "",
        "sale_price": p.get("sale_price") or "",
        "sku": p.get("sku") or "",
        "stock_status": p.get("stock_status") or "instock",
        "stock_quantity": p.get("stock_quantity"),
        "categories": [{"id": c["id"], "name": c["name"]} for c in p.get("categories", [])],
        "wc_date_modified": p.get("date_modified_gmt") or None,
    }


async def fetch_product_prices(product_ids: list[int], force: bool = False) -> dict[int, dict]:
    """Return {product_id: {...}} for every ID. Uses cache + parallel requests.
    Pass force=True to bypass cache entirely (manual user fetch)."""
    if not product_ids:
        return {}

    result: dict[int, dict] = {}

    # Serve cached entries first (skipped when force=True)
    uncached = []
    for pid in product_ids:
        cached = None if force else _cache_get(pid)
        if cached is not None:
            result[pid] = cached
        else:
            uncached.append(pid)

    needs_parent_fetch = any(
        data.get("parent_id", 0) > 0 and (
            not data.get("categories") or data.get("wc_date_modified") is None
        )
        for data in result.values()
    )

    if not uncached and not needs_parent_fetch:
        return result

    async with httpx.AsyncClient(auth=_auth(), timeout=90) as client:

        if uncached:
            # ── Phase 1: parallel batch requests (100 IDs each) ──────────────
            async def _fetch_batch(chunk: list[int]) -> list[dict]:
                params = [("include[]", str(pid)) for pid in chunk] + [
                    ("per_page", "100"),
                    ("status", "any"),
                    ("_fields", _PRODUCT_FIELDS),
                ]
                resp = await client.get(f"{_base()}/products", params=params)
                resp.raise_for_status()
                return resp.json()

            chunks = [uncached[i : i + 100] for i in range(0, len(uncached), 100)]
            batch_results = await asyncio.gather(*[_fetch_batch(c) for c in chunks], return_exceptions=True)

            for res in batch_results:
                if isinstance(res, Exception):
                    continue
                for p in res:
                    data = _parse_product(p)
                    result[p["id"]] = data
                    _cache_set(p["id"], data)

        # ── Phase 2: parallel individual lookups for missing IDs ─────────────
        missing = [pid for pid in uncached if pid not in result]

        async def _fetch_one(pid: int) -> tuple[int, dict] | None:
            try:
                resp = await client.get(
                    f"{_base()}/products/{pid}",
                    params={"_fields": _PRODUCT_FIELDS + ",parent_id", "status": "any"},
                )
                if resp.status_code == 200:
                    p = resp.json()
                    data = _parse_product(p)
                    data["parent_id"] = p.get("parent_id") or 0
                    if data["parent_id"] > 0:
                        data["wc_date_modified"] = None  # Phase 3 will set from parent
                    return p["id"], data
            except Exception:
                pass
            return None

        if missing:
            one_results = await asyncio.gather(*[_fetch_one(pid) for pid in missing])
            for r in one_results:
                if r is not None:
                    pid, data = r
                    result[pid] = data
                    _cache_set(pid, data)

        # ── Phase 3: inherit categories, stock, and modified date from parent ──
        # Variations don't carry categories or a meaningful modified date —
        # the product page shows the PARENT's post_modified, so we use that.
        parent_ids_needed = {
            data["parent_id"]
            for data in result.values()
            if data.get("parent_id", 0) > 0 and (
                not data.get("categories") or data.get("wc_date_modified") is None
            )
        }

        async def _fetch_parent(ppid: int) -> tuple[int, dict] | None:
            cached = _cache_get(ppid)
            if cached:
                return ppid, cached
            try:
                resp = await client.get(
                    f"{_base()}/products/{ppid}",
                    params={"_fields": "id,categories,stock_status,stock_quantity,date_modified_gmt"},
                )
                if resp.status_code == 200:
                    p = resp.json()
                    pdata = {
                        "categories": [{"id": c["id"], "name": c["name"]} for c in p.get("categories", [])],
                        "stock_quantity": p.get("stock_quantity"),
                        "wc_date_modified": p.get("date_modified_gmt") or None,
                    }
                    _cache_set(ppid, pdata)
                    return ppid, pdata
            except Exception:
                pass
            return None

        if parent_ids_needed:
            parent_results = await asyncio.gather(*[_fetch_parent(ppid) for ppid in parent_ids_needed])
            parent_map = {ppid: pdata for r in parent_results if r is not None for ppid, pdata in [r]}
            for data in result.values():
                ppid = data.get("parent_id", 0)
                if ppid and ppid in parent_map:
                    if not data.get("categories"):
                        data["categories"] = parent_map[ppid].get("categories", [])
                    if data.get("stock_quantity") is None:
                        data["stock_quantity"] = parent_map[ppid].get("stock_quantity")
                    # Always override variation's date with parent's — this is
                    # what article:modified_time and the product page widget show
                    data["wc_date_modified"] = parent_map[ppid].get("wc_date_modified")

    global _cache_last_populated
    _cache_last_populated = time.time()
    return result


async def fetch_categories() -> list[dict]:
    """Return all WooCommerce product categories as [{id, name}]."""
    categories: list[dict] = []
    page = 1
    async with httpx.AsyncClient(auth=_auth(), timeout=30) as client:
        while True:
            resp = await client.get(
                f"{_base()}/products/categories",
                params={"per_page": "100", "page": str(page), "_fields": "id,name"},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            categories.extend({"id": c["id"], "name": c["name"]} for c in data)
            if len(data) < 100:
                break
            page += 1
    return categories


async def update_single_product(product_id: int, updates: dict, parent_id: int = 0) -> dict:
    """PUT a single product or variation with arbitrary field updates."""
    async with httpx.AsyncClient(auth=_auth(), timeout=30) as client:
        if parent_id and parent_id > 0:
            url = f"{_base()}/products/{parent_id}/variations/{product_id}"
        else:
            url = f"{_base()}/products/{product_id}"
        resp = await client.put(url, json=updates)
        resp.raise_for_status()
        data = _parse_product(resp.json())
        _cache_set(product_id, data)
        return data


async def batch_update_prices(updates: list[dict]) -> list[dict]:
    """
    updates: [{product_id, new_price, parent_id}, ...]
    parent_id=0 means regular product; non-zero means variation.
    """
    def _parse_results(api_items: list) -> list[dict]:
        out = []
        for item in api_items:
            pid = item.get("id")
            err = item.get("error")
            if err:
                out.append({"product_id": pid, "success": False, "error_message": err.get("message", "Unknown WooCommerce error")})
            else:
                out.append({"product_id": pid, "success": True, "error_message": None})
        return out

    regular = [u for u in updates if not u.get("parent_id")]
    variations_by_parent: dict[int, list] = {}
    for u in updates:
        pid = u.get("parent_id") or 0
        if pid:
            variations_by_parent.setdefault(pid, []).append(u)

    results: list[dict] = []
    async with httpx.AsyncClient(auth=_auth(), timeout=60) as client:

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        async def _post_batch(url: str, chunk: list[dict]) -> list[dict]:
            def _item(u: dict) -> dict:
                d: dict = {"id": u["product_id"], "regular_price": u["new_price"], "date_modified_gmt": now_iso}
                if "stock_status" in u:
                    d["stock_status"] = u["stock_status"]
                return d
            payload = {"update": [_item(u) for u in chunk]}
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return _parse_results(resp.json().get("update", []))

        tasks = []
        base = _base()
        for i in range(0, len(regular), 100):
            tasks.append(_post_batch(f"{base}/products/batch", regular[i : i + 100]))
        for parent_id, var_updates in variations_by_parent.items():
            for i in range(0, len(var_updates), 100):
                tasks.append(_post_batch(f"{base}/products/{parent_id}/variations/batch", var_updates[i : i + 100]))

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in batch_results:
            if isinstance(res, Exception):
                raise res
            results.extend(res)

    return results


async def fetch_all_variations_stock(parent_id: int) -> list[dict]:
    """Return [{id, stock_status}] for every variation of a parent product."""
    variations: list[dict] = []
    page = 1
    async with httpx.AsyncClient(auth=_auth(), timeout=30) as client:
        while True:
            resp = await client.get(
                f"{_base()}/products/{parent_id}/variations",
                params={"per_page": "100", "page": str(page), "_fields": "id,stock_status"},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            variations.extend({"id": v["id"], "stock_status": v.get("stock_status", "outofstock")} for v in data)
            if len(data) < 100:
                break
            page += 1
    return variations


async def update_parent_stock_statuses(parent_statuses: dict[int, str]) -> None:
    """Batch-update stock_status on parent variable products."""
    if not parent_statuses:
        return
    async with httpx.AsyncClient(auth=_auth(), timeout=60) as client:
        async def _update_one(pid: int, status: str) -> None:
            try:
                resp = await client.put(
                    f"{_base()}/products/{pid}",
                    json={"stock_status": status},
                )
                resp.raise_for_status()
                cached = _cache_get(pid)
                if cached:
                    cached["stock_status"] = status
            except Exception:
                pass
        await asyncio.gather(*[_update_one(pid, s) for pid, s in parent_statuses.items()])
