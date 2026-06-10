from datetime import datetime, timedelta

import httpx
import jwt

from ..config import get_settings


async def verify_nextcloud_credentials(username: str, password: str) -> bool:
    """Verify a Nextcloud username/password via the OCS API."""
    s = get_settings()
    url = s.nextcloud_url.rstrip("/") + "/ocs/v2.php/cloud/user?format=json"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, auth=(username, password), headers={"OCS-APIRequest": "true"})
            if resp.status_code == 200:
                data = resp.json()
                statuscode = data.get("ocs", {}).get("meta", {}).get("statuscode")
                return statuscode == 200
    except Exception:
        pass
    return False


def is_super_admin(username: str) -> bool:
    s = get_settings()
    admins = [u.strip() for u in s.super_admin_users.split(",") if u.strip()]
    return username in admins


def create_token(username: str) -> str:
    s = get_settings()
    payload = {
        "sub": username,
        "role": "admin" if is_super_admin(username) else "user",
        "exp": datetime.utcnow() + timedelta(days=7),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=["HS256"])
