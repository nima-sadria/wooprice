import httpx

from ..config import get_settings


def _auth() -> tuple[str, str]:
    s = get_settings()
    return (s.wc_key, s.wc_secret)


def _base() -> str:
    return get_settings().wc_url.rstrip("/") + "/wp-json/wc/v3"


_PRODUCT_FIELDS = "id,name,regular_price,sale_price,price,sku,stock_status,stock_quantity,categories"


def _parse_product(p: dict) -> dict:
    return {
        "name": p.get("name", ""),
        "price": p.get("regular_price") or p.get("price") or "",
        "sale_price": p.get("sale_price") or "",
        "sku": p.get("sku") or "",
        "stock_status": p.get("stock_status") or "instock",
        "stock_quantity": p.get("stock_quantity"),
        "categories": [{"id": c["id"], "name": c["name"]} for c in p.get("categories", [])],
    }


async def fetch_product_prices(product_ids: list[int]) -> dict[int, dict]:
    """Return {product_id: {name, price, sale_price, sku, stock_status, stock_quantity, categories}} for every ID."""
    if not product_ids:
        return {}

    result: dict[int, dict] = {}
    async with httpx.AsyncClient(auth=_auth(), timeout=30) as client:
        for i in range(0, len(product_ids), 100):
            chunk = product_ids[i : i + 100]
            params = [("include[]", str(pid)) for pid in chunk] + [
                ("per_page", "100"),
                ("status", "any"),
                ("_fields", _PRODUCT_FIELDS),
            ]
            resp = await client.get(f"{_base()}/products", params=params)
            resp.raise_for_status()
            for p in resp.json():
                result[p["id"]] = _parse_product(p)

        missing = [pid for pid in product_ids if pid not in result]
        for pid in missing:
            resp = await client.get(
                f"{_base()}/products/{pid}",
                params={"_fields": _PRODUCT_FIELDS + ",parent_id"},
            )
            if resp.status_code == 200:
                p = resp.json()
                data = _parse_product(p)
                data["parent_id"] = p.get("parent_id") or 0
                result[p["id"]] = data

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
        for i in range(0, len(regular), 100):
            chunk = regular[i : i + 100]
            payload = {"update": [{"id": u["product_id"], "regular_price": u["new_price"]} for u in chunk]}
            resp = await client.post(f"{_base()}/products/batch", json=payload)
            resp.raise_for_status()
            results.extend(_parse_results(resp.json().get("update", [])))

        for parent_id, var_updates in variations_by_parent.items():
            for i in range(0, len(var_updates), 100):
                chunk = var_updates[i : i + 100]
                payload = {"update": [{"id": u["product_id"], "regular_price": u["new_price"]} for u in chunk]}
                resp = await client.post(f"{_base()}/products/{parent_id}/variations/batch", json=payload)
                resp.raise_for_status()
                results.extend(_parse_results(resp.json().get("update", [])))

    return results
