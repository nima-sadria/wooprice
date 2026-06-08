import httpx

from ..config import get_settings


def _auth() -> tuple[str, str]:
    s = get_settings()
    return (s.wc_key, s.wc_secret)


def _base() -> str:
    return get_settings().wc_url.rstrip("/") + "/wp-json/wc/v3"


async def fetch_product_prices(product_ids: list[int]) -> dict[int, dict]:
    """Return {product_id: {name, price}} for every ID in the list."""
    if not product_ids:
        return {}

    result: dict[int, dict] = {}
    async with httpx.AsyncClient(auth=_auth(), timeout=30) as client:
        # Batch fetch for regular products
        for i in range(0, len(product_ids), 100):
            chunk = product_ids[i : i + 100]
            params = [("include[]", str(pid)) for pid in chunk] + [
                ("per_page", "100"),
                ("_fields", "id,name,regular_price,price"),
            ]
            resp = await client.get(f"{_base()}/products", params=params)
            resp.raise_for_status()
            for p in resp.json():
                result[p["id"]] = {
                    "name": p.get("name", ""),
                    "price": p.get("regular_price") or p.get("price") or "",
                }

        # Fallback: fetch individually for IDs not found (e.g. variations)
        missing = [pid for pid in product_ids if pid not in result]
        for pid in missing:
            resp = await client.get(
                f"{_base()}/products/{pid}",
                params={"_fields": "id,name,regular_price,price,parent_id"},
            )
            if resp.status_code == 200:
                p = resp.json()
                result[p["id"]] = {
                    "name": p.get("name", ""),
                    "price": p.get("regular_price") or p.get("price") or "",
                    "parent_id": p.get("parent_id") or 0,
                }

    return result


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
        # Regular products via /products/batch
        for i in range(0, len(regular), 100):
            chunk = regular[i : i + 100]
            payload = {"update": [{"id": u["product_id"], "regular_price": u["new_price"]} for u in chunk]}
            resp = await client.post(f"{_base()}/products/batch", json=payload)
            resp.raise_for_status()
            results.extend(_parse_results(resp.json().get("update", [])))

        # Variations via /products/{parent_id}/variations/batch
        for parent_id, var_updates in variations_by_parent.items():
            for i in range(0, len(var_updates), 100):
                chunk = var_updates[i : i + 100]
                payload = {"update": [{"id": u["product_id"], "regular_price": u["new_price"]} for u in chunk]}
                resp = await client.post(f"{_base()}/products/{parent_id}/variations/batch", json=payload)
                resp.raise_for_status()
                results.extend(_parse_results(resp.json().get("update", [])))

    return results
