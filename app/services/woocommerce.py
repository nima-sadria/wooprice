import asyncio
import logging
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 3
_MAX_RETRY_SLEEP: float = 30.0        # cap per-retry Retry-After to 30 s
_MAX_TOTAL_RETRY_SLEEP: float = 90.0  # fail fast when total sleep exceeds 90 s


@dataclass
class FetchTelemetry:
    """Per-fetch metrics collected across all WC API requests in one operation."""
    product_pages: int = 0
    variation_pages: int = 0
    wc_requests: int = 0
    retry_count: int = 0
    retry_sleep_s: float = 0.0
    elapsed_s: float = 0.0
    cache_rows_updated: int = 0        # inserted + updated after upsert
    mode: str = ""                     # light | full | deep
    propagated_children: int = 0       # child rows updated by parent-metadata propagation
    capability_probe_requests: int = 0  # WC requests made during capability probe
    capability_probe_retries: int = 0   # retries during capability probe


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    telemetry: "FetchTelemetry | None" = None,
    method: str = "get",
    **kwargs,
) -> httpx.Response:
    """HTTP request with exponential backoff on 429/5xx.

    method: HTTP verb to use — "get" (default) for all normal fetches,
    "options" for capability probing.  All other behaviour is identical.
    """
    total_sleep = 0.0
    for attempt in range(_MAX_RETRIES + 1):
        resp = await getattr(client, method)(url, **kwargs)
        if telemetry is not None:
            telemetry.wc_requests += 1
        if resp.status_code not in _RETRY_STATUSES:
            resp.raise_for_status()
            return resp
        if attempt == _MAX_RETRIES:
            break
        retry_after = resp.headers.get("Retry-After")
        try:
            raw_wait = float(retry_after) if retry_after else float(2 ** attempt)
        except ValueError:
            raw_wait = float(2 ** attempt)
        wait = min(raw_wait, _MAX_RETRY_SLEEP)
        if total_sleep + wait >= _MAX_TOTAL_RETRY_SLEEP:
            logger.error(
                "WC retry budget exhausted (%.0fs slept so far) on %s — aborting fetch",
                total_sleep, url,
            )
            raise RuntimeError(
                f"WooCommerce retry budget exhausted after {total_sleep:.0f}s sleep. "
                "The API is rate-limiting or unavailable — wait a few minutes and try again."
            )
        logger.warning(
            "WC %d on %s — retry %d/%d in %.0fs (Retry-After: %s, capped from %.0fs)",
            resp.status_code, url, attempt + 1, _MAX_RETRIES, wait,
            retry_after or "none", raw_wait,
        )
        if telemetry is not None:
            telemetry.retry_count += 1
            telemetry.retry_sleep_s += wait
        await asyncio.sleep(wait)
        total_sleep += wait
    resp.raise_for_status()
    return resp  # unreachable; raise_for_status raises


def _auth() -> tuple[str, str]:
    s = get_settings()
    return (s.wc_key, s.wc_secret)


def _base() -> str:
    return get_settings().wc_url.rstrip("/") + "/wp-json/wc/v3"


_PRODUCT_FIELDS = "id,name,regular_price,sale_price,price,sku,stock_status,stock_quantity,categories,brands,attributes,date_modified_gmt"

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


def _extract_brand(p: dict) -> tuple[int | None, str | None]:
    """Return (brand_id, brand_name) from WC's native `brands` taxonomy field,
    falling back to the pa_brand-filter product attribute when no taxonomy
    entry is present.

    Primary: WC Brands taxonomy (top-level `brands: [{id, name, slug}]`).
    Fallback: pa_brand-filter attribute option (e.g. in catalogs that use the
    WooCommerce attribute taxonomy instead of the Brands plugin). The brand_id
    for pa_brand-filter entries is a stable crc32 of the brand name (attribute
    options don't expose term IDs in the products endpoint).
    brand_id=None means no brand at all — never guessed from name or other fields.
    """
    brands = p.get("brands") or []
    if brands:
        b = brands[0]
        return b.get("id"), b.get("name")
    for attr in (p.get("attributes") or []):
        slug = attr.get("slug") or attr.get("name") or ""
        if slug == "pa_brand-filter":
            options = attr.get("options") or []
            if options:
                name = str(options[0])
                # Stable positive integer derived from brand name (no term ID available)
                return zlib.crc32(name.encode()) & 0x7FFFFFFF, name
    return None, None


def _parse_product(p: dict) -> dict:
    brand_id, brand_name = _extract_brand(p)
    return {
        "name": p.get("name", ""),
        "price": p.get("regular_price") or p.get("price") or "",
        "sale_price": p.get("sale_price") or "",
        "sku": p.get("sku") or "",
        "stock_status": p.get("stock_status") or "instock",
        "stock_quantity": p.get("stock_quantity"),
        "categories": [{"id": c["id"], "name": c["name"]} for c in p.get("categories", [])],
        "brand_id": brand_id,
        "brand_name": brand_name,
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
            or "brand_id" not in data
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
                resp = await _get_with_retry(client, f"{_base()}/products", params=params)
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
                resp = await _get_with_retry(
                    client, f"{_base()}/products/{pid}",
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

        # ── Phase 3: inherit categories, brand, stock, and modified date from parent ──
        # Variations don't carry categories, a brand, or a meaningful modified date —
        # the product page shows the PARENT's post_modified, so we use that.
        parent_ids_needed = {
            data["parent_id"]
            for data in result.values()
            if data.get("parent_id", 0) > 0 and (
                not data.get("categories") or data.get("wc_date_modified") is None
                or "brand_id" not in data
            )
        }

        async def _fetch_parent(ppid: int) -> tuple[int, dict] | None:
            cached = _cache_get(ppid)
            # "brand_id" not in cached guards against a pre-existing in-memory
            # entry cached before brand support shipped — without this, a
            # stale cache hit here would silently report "no brand" instead
            # of actually fetching it.
            if cached and "brand_id" in cached:
                return ppid, cached
            try:
                resp = await _get_with_retry(
                    client, f"{_base()}/products/{ppid}",
                    params={"_fields": "id,categories,brands,stock_status,stock_quantity,date_modified_gmt"},
                )
                if resp.status_code == 200:
                    p = resp.json()
                    brand_id, brand_name = _extract_brand(p)
                    pdata = {
                        "categories": [{"id": c["id"], "name": c["name"]} for c in p.get("categories", [])],
                        "brand_id": brand_id,
                        "brand_name": brand_name,
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
                    # Variations never carry their own `brands` field — always
                    # inherit the parent's brand (confirmed via live audit).
                    data["brand_id"] = parent_map[ppid].get("brand_id")
                    data["brand_name"] = parent_map[ppid].get("brand_name")
                    # Always override variation's date with parent's — this is
                    # what article:modified_time and the product page widget show
                    data["wc_date_modified"] = parent_map[ppid].get("wc_date_modified")

    global _cache_last_populated
    _cache_last_populated = time.time()
    return result


async def fetch_categories() -> list[dict]:
    """Return all WooCommerce product categories as [{id, name, parent}].

    parent == 0 means top-level category; otherwise it's the parent category's id.
    """
    categories: list[dict] = []
    page = 1
    async with httpx.AsyncClient(auth=_auth(), timeout=30) as client:
        while True:
            resp = await _get_with_retry(
                client, f"{_base()}/products/categories",
                params={"per_page": "100", "page": str(page), "_fields": "id,name,parent"},
            )
            data = resp.json()
            if not data:
                break
            categories.extend({"id": c["id"], "name": c["name"], "parent": c.get("parent", 0)} for c in data)
            if len(data) < 100:
                break
            page += 1
    return categories


async def lookup_product_info(product_id: int) -> dict:
    """
    Look up a product directly from WooCommerce.
    Returns {wc_id, product_type, parent_id, name, sku, found, source}.
    Tries /products/{id} first; 404 means it is likely a variation
    (WC REST does not expose variations via top-level /products/{id}).
    """
    async with httpx.AsyncClient(auth=_auth(), timeout=30) as client:
        resp = await client.get(
            f"{_base()}/products/{product_id}",
            params={"_fields": "id,type,name,sku,parent_id,status"},
        )
        if resp.status_code == 200:
            p = resp.json()
            return {
                "found": True,
                "source": "woocommerce",
                "wc_id": p.get("id"),
                "product_type": p.get("type", "simple"),
                "parent_id": p.get("parent_id") or 0,
                "name": p.get("name", ""),
                "sku": p.get("sku", ""),
                "status": p.get("status", ""),
            }
        if resp.status_code == 404:
            return {
                "found": False,
                "source": "woocommerce",
                "wc_id": product_id,
                "note": (
                    "Not found as a top-level product. "
                    "If this is a variation, parent_id is required to update it. "
                    "Run GET /api/fetch/full to populate the local cache with parent_id data."
                ),
            }
        resp.raise_for_status()
        return {"found": False, "source": "woocommerce", "wc_id": product_id}


async def resolve_variation_parent_id(variation_id: int) -> int | None:
    """Best-effort WC lookup to find parent_id for an unknown variation ID.

    Uses a 5-second timeout so the thumbnail endpoint never hangs.
    Returns parent_id > 0 if the ID is a variation, None otherwise.
    """
    try:
        async with httpx.AsyncClient(auth=_auth(), timeout=5) as client:
            resp = await client.get(
                f"{_base()}/products/{variation_id}",
                params={"_fields": "id,parent_id,type"},
            )
            if resp.status_code == 200:
                data = resp.json()
                parent_id = data.get("parent_id") or 0
                if parent_id > 0:
                    logger.info(
                        "resolve_variation_parent_id: wc_id=%d → parent_id=%d (type=%s)",
                        variation_id, parent_id, data.get("type", "?"),
                    )
                    return parent_id
    except Exception as exc:
        logger.warning("resolve_variation_parent_id: failed for wc_id=%d: %s", variation_id, exc)
    return None


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


_FULL_FIELDS = "id,name,type,sku,regular_price,sale_price,price,stock_status,stock_quantity,manage_stock,categories,brands,attributes,date_modified_gmt,status,images"
_VAR_FIELDS = "id,sku,regular_price,sale_price,price,stock_status,stock_quantity,manage_stock,date_modified_gmt,image"


def _extract_image(p: dict, parent_id: int, parent_image: str | None) -> tuple[str | None, str]:
    """Return (image_url, image_source) for a product or variation."""
    if parent_id > 0:
        # Variation: WC uses singular 'image' key
        var_img = p.get("image") or {}
        url = var_img.get("src") or ""
        if url:
            return url, "variation"
        if parent_image:
            return parent_image, "parent"
        return None, "none"
    # Simple or variable parent: WC uses plural 'images' array
    images = p.get("images") or []
    url = images[0].get("src", "") if images else ""
    return (url or None), ("simple" if url else "none")


def _parse_full_product(
    p: dict,
    parent_id: int = 0,
    parent_cats: list | None = None,
    parent_image: str | None = None,
    parent_brand: tuple[int | None, str | None] | None = None,
) -> dict:
    cats = parent_cats if parent_cats is not None else [
        {"id": c["id"], "name": c["name"]} for c in p.get("categories", [])
    ]
    if parent_id > 0:
        # Variations never carry their own `brands` field (confirmed via live
        # audit) — always inherit the parent's brand. Never guessed otherwise.
        brand_id, brand_name = parent_brand if parent_brand is not None else (None, None)
    else:
        brand_id, brand_name = _extract_brand(p)
    ptype = "variation" if parent_id > 0 else (p.get("type") or "simple")
    img_url, img_source = _extract_image(p, parent_id, parent_image)
    raw_ms = p.get("manage_stock")
    if isinstance(raw_ms, bool):
        manage_stock = "true" if raw_ms else "false"
    elif raw_ms is not None:
        manage_stock = str(raw_ms).lower()
    else:
        manage_stock = None
    return {
        "wc_id": p["id"],
        "parent_id": parent_id,
        "product_type": ptype,
        "sku": p.get("sku", ""),
        "name": p.get("name", ""),
        "status": p.get("status", "publish"),
        "stock_status": p.get("stock_status", "instock"),
        "stock_quantity": p.get("stock_quantity"),
        "manage_stock": manage_stock,
        "regular_price": p.get("regular_price", ""),
        "sale_price": p.get("sale_price", ""),
        "final_price": p.get("regular_price") or p.get("price", ""),
        "categories": cats,
        "brand_id": brand_id,
        "brand_name": brand_name,
        "date_modified_gmt": p.get("date_modified_gmt", ""),
        "image_url": img_url,
        "image_source": img_source,
    }


async def _fetch_variations_for_parent(
    client: httpx.AsyncClient,
    parent_id: int,
    parent_name: str,
    parent_cats: list,
    parent_image: str | None = None,
    parent_brand: tuple[int | None, str | None] | None = None,
    telemetry: "FetchTelemetry | None" = None,
) -> list[dict]:
    variations = []
    page = 1
    while True:
        resp = await _get_with_retry(
            client, f"{_base()}/products/{parent_id}/variations",
            telemetry=telemetry,
            params={"per_page": "100", "page": str(page), "status": "any", "_fields": _VAR_FIELDS},
        )
        if telemetry is not None:
            telemetry.variation_pages += 1
        data = resp.json()
        if not data:
            break
        for v in data:
            v["name"] = parent_name
            parsed = _parse_full_product(
                v, parent_id=parent_id, parent_cats=parent_cats, parent_image=parent_image,
                parent_brand=parent_brand,
            )
            logger.debug(
                "full_fetch variation: wc_id=%s parent_id=%s image_source=%s image_url=%s",
                parsed["wc_id"], parent_id, parsed["image_source"], parsed["image_url"] or "NULL",
            )
            variations.append(parsed)
        if len(data) < 100:
            break
        page += 1
    logger.debug(
        "full_fetch: fetched %d variation(s) for parent_id=%d parent_image=%s",
        len(variations), parent_id, parent_image or "NULL",
    )
    return variations


async def fetch_all_products_fast(
    telemetry: "FetchTelemetry | None" = None,
) -> tuple[list[dict], list[str]]:
    """Fetch all top-level products (simple + variable parents) — no variation sub-requests.

    Runs ~24 WC API pages instead of 2000+ variation calls.  Variable parent rows get the
    parent's own image so thumbnails work immediately.  Variation rows are not created here;
    use fetch_variations_for_selected_parents() for targeted variation refreshes.
    """
    logger.warning("FETCH_ROUTE_ENTERED: route=fetch_all_products_fast mode=fast_no_variations")
    all_products: list[dict] = []

    try:
        async with httpx.AsyncClient(auth=_auth(), timeout=120) as client:
            page = 1
            while True:
                resp = await _get_with_retry(
                    client, f"{_base()}/products",
                    telemetry=telemetry,
                    params={"per_page": "100", "page": str(page), "status": "any", "_fields": _FULL_FIELDS},
                )
                if telemetry is not None:
                    telemetry.product_pages += 1
                data = resp.json()
                if not data:
                    break
                for p in data:
                    all_products.append(_parse_full_product(p))
                if len(data) < 100:
                    break
                page += 1
    except Exception:
        record_wc_failure()
        raise

    record_wc_success()
    variable_count = sum(1 for p in all_products if p.get("product_type") == "variable")
    logger.info(
        "fast_fetch: done — %d products (%d variable parents, no variations fetched)",
        len(all_products), variable_count,
    )
    return all_products, []


async def fetch_variations_for_selected_parents(
    parent_ids: set[int],
    parent_info: dict[int, tuple[str, list, str | None, tuple[int | None, str | None] | None]],
    concurrency: int = 5,
) -> tuple[list[dict], list[str]]:
    """Fetch WC variations only for the given parent IDs.

    parent_info: {parent_id: (name, categories_list, image_url_or_none, (brand_id, brand_name)_or_none)}
    Call this with IDs present in the spreadsheet/preview — never globally.
    """
    if not parent_ids:
        return [], []

    all_variations: list[dict] = []
    var_warnings: list[str] = []
    sem = asyncio.Semaphore(concurrency)
    plist = list(parent_ids)

    async with httpx.AsyncClient(auth=_auth(), timeout=120) as client:
        async def _bounded(pid: int):
            async with sem:
                name, cats, img, brand = parent_info.get(pid, ("", [], None, None))
                try:
                    return await _fetch_variations_for_parent(client, pid, name, cats, img, brand)
                except Exception as exc:
                    logger.warning("targeted_variation_fetch: failed for parent #%d: %s", pid, exc)
                    return exc

        results = await asyncio.gather(*[_bounded(pid) for pid in plist])
        for i, r in enumerate(results):
            if isinstance(r, list):
                all_variations.extend(r)
            else:
                var_warnings.append(f"Variation fetch failed for parent #{plist[i]}: {r}")

    logger.info(
        "targeted_variation_fetch: done — %d variations for %d parents (%d warnings)",
        len(all_variations), len(parent_ids), len(var_warnings),
    )
    return all_variations, var_warnings


async def fetch_all_products_full(
    telemetry: "FetchTelemetry | None" = None,
) -> tuple[list[dict], list[str]]:
    """Fetch ALL products and their variations from WooCommerce for full cache population.
    Returns (products, variation_warnings) where warnings list is non-empty if any
    variation fetches failed after all retries."""
    logger.warning("FETCH_ROUTE_ENTERED: route=fetch_all_products_full mode=wc_full_api_sync")
    all_products: list[dict] = []
    variable_parents: list[tuple[int, str, list, str | None, tuple[int | None, str | None]]] = []
    var_warnings: list[str] = []

    try:
        async with httpx.AsyncClient(auth=_auth(), timeout=120) as client:
            page = 1
            while True:
                resp = await _get_with_retry(
                    client, f"{_base()}/products",
                    telemetry=telemetry,
                    params={"per_page": "100", "page": str(page), "status": "any", "_fields": _FULL_FIELDS},
                )
                if telemetry is not None:
                    telemetry.product_pages += 1
                data = resp.json()
                if not data:
                    break
                for p in data:
                    cats = [{"id": c["id"], "name": c["name"]} for c in p.get("categories", [])]
                    images = p.get("images") or []
                    parent_img = images[0].get("src", "") if images else ""
                    all_products.append(_parse_full_product(p))
                    if p.get("type") == "variable":
                        logger.debug(
                            "full_fetch: variable parent pid=%d name=%r img=%s",
                            p["id"], p.get("name", ""), parent_img or "none",
                        )
                        variable_parents.append((p["id"], p.get("name", ""), cats, parent_img or None, _extract_brand(p)))
                if len(data) < 100:
                    break
                page += 1

            logger.info(
                "full_fetch: phase1 done — %d top-level products, %d variable parents",
                len(all_products), len(variable_parents),
            )

            for i in range(0, len(variable_parents), 10):
                batch = variable_parents[i:i + 10]
                results = await asyncio.gather(*[
                    _fetch_variations_for_parent(client, pid, name, cats, parent_img, parent_brand, telemetry=telemetry)
                    for pid, name, cats, parent_img, parent_brand in batch
                ], return_exceptions=True)
                for j, r in enumerate(results):
                    if isinstance(r, list):
                        all_products.extend(r)
                    else:
                        parent_id, parent_name = batch[j][0], batch[j][1]
                        msg = f"Variation fetch failed for parent #{parent_id} ({parent_name}): {r}"
                        logger.warning(msg)
                        var_warnings.append(msg)
    except Exception:
        record_wc_failure()
        raise

    record_wc_success()
    logger.info(
        "full_fetch: complete — %d total products (top-level + variations), %d warnings",
        len(all_products), len(var_warnings),
    )
    return all_products, var_warnings


async def _fetch_variations_modified_after(
    client: httpx.AsyncClient,
    parent_id: int,
    parent_name: str,
    parent_cats: list,
    parent_image: str | None,
    parent_brand: tuple[int | None, str | None] | None,
    modified_after: str,
    modified_before: str,
    telemetry: "FetchTelemetry | None" = None,
) -> list[dict]:
    """Fetch variations for one parent that were modified in [modified_after, modified_before].

    Stops after the first empty page — if WC returns no results, there are no
    modified variations for this parent and we do not crawl further.
    Deep Sync remains the only operation that fetches ALL variations.
    """
    variations: list[dict] = []
    page = 1
    while True:
        resp = await _get_with_retry(
            client, f"{_base()}/products/{parent_id}/variations",
            telemetry=telemetry,
            params={
                "per_page": "100", "page": str(page),
                "status": "any", "_fields": _VAR_FIELDS,
                "modified_after": modified_after,
                "modified_before": modified_before,
                "dates_are_gmt": "true",
            },
        )
        if telemetry is not None:
            telemetry.variation_pages += 1
        data = resp.json()
        if not data:
            break
        for v in data:
            v["name"] = parent_name
            variations.append(
                _parse_full_product(
                    v, parent_id=parent_id,
                    parent_cats=parent_cats,
                    parent_image=parent_image,
                    parent_brand=parent_brand,
                )
            )
        if len(data) < 100:
            break
        page += 1
    logger.debug(
        "light_fetch: %d modified variation(s) for parent_id=%d in window",
        len(variations), parent_id,
    )
    return variations


async def fetch_products_light(
    modified_after: str,
    modified_before: str,
    telemetry: "FetchTelemetry | None" = None,
) -> tuple[list[dict], list[str]]:
    """Light sync: fetch only top-level products and their modified variations
    in the half-open window (modified_after, modified_before], using WC GMT times.

    For variable parents in the result set, only variations modified in the same
    window are fetched — stops on first empty page per parent.
    Deep Sync remains the only operation that crawls ALL variations globally.

    Returns (products, variation_warnings).
    """
    all_products: list[dict] = []
    variable_parents: list[tuple[int, str, list, str | None, tuple[int | None, str | None]]] = []
    var_warnings: list[str] = []

    try:
        async with httpx.AsyncClient(auth=_auth(), timeout=120) as client:
            # Phase 1: modified top-level products
            page = 1
            while True:
                resp = await _get_with_retry(
                    client, f"{_base()}/products",
                    telemetry=telemetry,
                    params={
                        "per_page": "100", "page": str(page),
                        "status": "any", "_fields": _FULL_FIELDS,
                        "modified_after": modified_after,
                        "modified_before": modified_before,
                        "dates_are_gmt": "true",
                    },
                )
                if telemetry is not None:
                    telemetry.product_pages += 1
                data = resp.json()
                if not data:
                    break
                for p in data:
                    cats = [{"id": c["id"], "name": c["name"]} for c in p.get("categories", [])]
                    images = p.get("images") or []
                    parent_img = images[0].get("src", "") if images else ""
                    all_products.append(_parse_full_product(p))
                    if p.get("type") == "variable":
                        variable_parents.append(
                            (p["id"], p.get("name", ""), cats, parent_img or None, _extract_brand(p))
                        )
                if len(data) < 100:
                    break
                page += 1

            logger.info(
                "light_fetch: phase1 done — %d modified top-level product(s), %d variable parent(s)",
                len(all_products), len(variable_parents),
            )

            # Phase 2: for each modified variable parent, fetch only its modified variations
            for i in range(0, len(variable_parents), 10):
                batch = variable_parents[i:i + 10]
                results = await asyncio.gather(*[
                    _fetch_variations_modified_after(
                        client, pid, name, cats, parent_img, parent_brand,
                        modified_after=modified_after,
                        modified_before=modified_before,
                        telemetry=telemetry,
                    )
                    for pid, name, cats, parent_img, parent_brand in batch
                ], return_exceptions=True)
                for j, r in enumerate(results):
                    if isinstance(r, list):
                        all_products.extend(r)
                    else:
                        parent_id, parent_name = batch[j][0], batch[j][1]
                        msg = f"Light variation fetch failed for parent #{parent_id} ({parent_name}): {r}"
                        logger.warning(msg)
                        var_warnings.append(msg)
    except Exception:
        record_wc_failure()
        raise

    record_wc_success()
    logger.info(
        "light_fetch: complete — %d total records (top-level + modified variations), %d warnings",
        len(all_products), len(var_warnings),
    )
    return all_products, var_warnings


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


# ── WooCommerce connectivity health state ─────────────────────────────────────
# Records the epoch of the most recent successful/failed WC network access.
# Used by /api/health to derive status without live probes.
_wc_last_success_ts: float = 0.0
_wc_last_failure_ts: float = 0.0


def record_wc_success() -> None:
    global _wc_last_success_ts
    _wc_last_success_ts = time.time()


def record_wc_failure() -> None:
    global _wc_last_failure_ts
    _wc_last_failure_ts = time.time()


def reset_wc_health_state() -> None:
    global _wc_last_success_ts, _wc_last_failure_ts
    _wc_last_success_ts = 0.0
    _wc_last_failure_ts = 0.0


_wc_variation_filter_capable: bool | None = None  # None = not yet checked


def _schema_supports_modified_after(data: dict) -> bool:
    """Return True if the WC OPTIONS response schema declares modified_after as a GET arg."""
    routes = data.get("routes", {})
    for route_data in routes.values():
        for ep in route_data.get("endpoints", []):
            if "GET" in ep.get("methods", []):
                if "modified_after" in ep.get("args", {}):
                    return True
    # Some WC versions return endpoints at the top level
    for ep in data.get("endpoints", []):
        if "GET" in ep.get("methods", []):
            if "modified_after" in ep.get("args", {}):
                return True
    return False


async def check_variation_filter_capability(
    db,
    telemetry: "FetchTelemetry | None" = None,
) -> bool | None:
    """Verify the variation endpoint honours modified_after + dates_are_gmt.

    Strategy: OPTIONS request (routed through _get_with_retry for 429/5xx
    backoff) to the variation endpoint; inspect the schema's GET args.
    Only marks capability True when the schema *explicitly* declares modified_after.

    Cache states
    ────────────
    True  — schema confirmed modified_after supported (cached)
    False — schema explicitly omits modified_after (cached)
    None  — retry exhaustion / timeout / auth / transport / malformed response (NOT cached)

    No variable parent: returns True without caching (no variations to filter).
    """
    global _wc_variation_filter_capable
    if _wc_variation_filter_capable is not None:
        return _wc_variation_filter_capable

    from ..models import ProductCache as _PC
    parent_row = (
        db.query(_PC.wc_id)
        .filter(_PC.parent_id == 0, _PC.product_type == "variable")
        .first()
    )
    if parent_row is None:
        # No variable product — cannot prove capability.  Do NOT cache: a later
        # Deep Sync may add variable products and we must re-probe then.
        # Return True so simple-product-only stores can still Light Refresh.
        logger.info(
            "wc_capability: no variable parent in cache — skipping probe, "
            "variations will not be fetched during Light Refresh"
        )
        return True

    test_pid = parent_row.wc_id
    _probe_telem = FetchTelemetry()
    try:
        async with httpx.AsyncClient(auth=_auth(), timeout=30) as client:
            resp = await _get_with_retry(
                client,
                f"{_base()}/products/{test_pid}/variations",
                telemetry=_probe_telem,
                method="options",
            )
        if telemetry is not None:
            telemetry.capability_probe_requests += _probe_telem.wc_requests
            telemetry.capability_probe_retries += _probe_telem.retry_count

        if resp.status_code == 200:
            record_wc_success()
            try:
                schema = resp.json()
            except Exception:
                # WC responded but body is not parseable — connectivity confirmed,
                # capability indeterminate. Do NOT cache so next call can re-probe.
                logger.warning(
                    "wc_capability: OPTIONS returned 200 but body is not valid JSON "
                    "— capability indeterminate (not cached)"
                )
                return None
            if _schema_supports_modified_after(schema):
                logger.info(
                    "wc_capability: variation modified_after filter confirmed via OPTIONS schema"
                )
                _wc_variation_filter_capable = True
                return True
            logger.warning(
                "wc_capability: OPTIONS schema does not declare modified_after — "
                "Light Refresh variation filtering unsupported"
            )
            _wc_variation_filter_capable = False
            return False
        else:
            # WC is reachable (it responded); non-200 status is not a network failure.
            # Capability cannot be determined from this response — do NOT cache.
            record_wc_success()
            logger.warning(
                "wc_capability: OPTIONS returned %d — capability indeterminate (not cached)",
                resp.status_code,
            )
            return None

    except RuntimeError:
        # Retry budget exhausted — connectivity/rate-limit failure, NOT a confirmed schema
        # check. Do NOT cache: allows re-probe on next call once the API recovers.
        record_wc_failure()
        if telemetry is not None:
            telemetry.capability_probe_requests += _probe_telem.wc_requests
            telemetry.capability_probe_retries += _probe_telem.retry_count
        logger.warning(
            "wc_capability: OPTIONS retry budget exhausted after %d requests, "
            "%d retries — capability indeterminate (not cached)",
            _probe_telem.wc_requests, _probe_telem.retry_count,
        )
        return None

    except Exception as exc:
        # Transient / unexpected error — do NOT cache; allow re-probe on next call.
        record_wc_failure()
        if telemetry is not None:
            telemetry.capability_probe_requests += _probe_telem.wc_requests
            telemetry.capability_probe_retries += _probe_telem.retry_count
        logger.warning(
            "wc_capability: OPTIONS probe error (result not cached, will retry): %s", exc
        )
        return None


def reset_wc_capability_cache() -> None:
    """Reset the cached capability check result (used in tests and on reconnect)."""
    global _wc_variation_filter_capable
    _wc_variation_filter_capable = None
