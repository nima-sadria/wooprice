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
        for i in range(0, len(product_ids), 100):
            chunk = product_ids[i : i + 100]
            resp = await client.get(
                f"{_base()}/products",
                params={
                    "include": ",".join(str(x) for x in chunk),
                    "per_page": 100,
                    "_fields": "id,name,regular_price,price",
                },
            )
            resp.raise_for_status()
            for p in resp.json():
                result[p["id"]] = {
                    "name": p.get("name", ""),
                    "price": p.get("regular_price") or p.get("price") or "",
                }
    return result


async def batch_update_prices(updates: list[dict]) -> list[dict]:
    """
    updates: [{product_id, new_price}, ...]
    Returns [{product_id, success, error_message}, ...]
    Uses the WooCommerce batch endpoint (max 100 per request).
    """
    results: list[dict] = []
    async with httpx.AsyncClient(auth=_auth(), timeout=60) as client:
        for i in range(0, len(updates), 100):
            chunk = updates[i : i + 100]
            payload = {
                "update": [
                    {"id": u["product_id"], "regular_price": u["new_price"]}
                    for u in chunk
                ]
            }
            resp = await client.post(f"{_base()}/products/batch", json=payload)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("update", []):
                pid = item.get("id")
                err = item.get("error")
                if err:
                    results.append(
                        {
                            "product_id": pid,
                            "success": False,
                            "error_message": err.get("message", "Unknown WooCommerce error"),
                        }
                    )
                else:
                    results.append(
                        {"product_id": pid, "success": True, "error_message": None}
                    )
    return results
