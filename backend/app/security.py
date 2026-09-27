from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    role: str
    subject: str


bearer = HTTPBearer(auto_error=False)
ROLE_LEVEL = {"viewer": 1, "analyst": 2, "admin": 3}


def _configured_keys() -> list[dict[str, str]]:
    raw = os.getenv("TRUSTMESH_API_KEYS", "")
    if not raw:
        return []
    try:
        keys = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="TRUSTMESH_API_KEYS must be valid JSON") from exc
    if not isinstance(keys, list) or any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("token"), str)
        or not isinstance(entry.get("tenant_id"), str)
        or not isinstance(entry.get("role"), str)
        for entry in keys
    ):
        raise HTTPException(
            status_code=500,
            detail="TRUSTMESH_API_KEYS must be a list of token, tenant_id, role objects",
        )
    return keys


def authentication_required() -> bool:
    return os.getenv("APP_ENV", "development").lower() == "production" or bool(_configured_keys())


def current_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> Principal:
    keys = _configured_keys()
    production = os.getenv("APP_ENV", "development").lower() == "production"
    if not keys and not production:
        return Principal("default", "admin", "local-development")
    if not credentials:
        raise HTTPException(status_code=401, detail="Bearer API token required")
    for entry in keys:
        token = entry.get("token", "")
        if token and hmac.compare_digest(credentials.credentials, token):
            role = entry.get("role", "")
            tenant_id = entry.get("tenant_id", "")
            if role not in ROLE_LEVEL or not tenant_id:
                raise HTTPException(status_code=500, detail="Invalid API key role or tenant configuration")
            return Principal(tenant_id, role, entry.get("subject", "api-client"))
    raise HTTPException(status_code=401, detail="Invalid API token")


def require_role(minimum_role: str) -> Callable:
    required_level = ROLE_LEVEL[minimum_role]

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if ROLE_LEVEL.get(principal.role, 0) < required_level:
            raise HTTPException(status_code=403, detail="Insufficient role for this operation")
        return principal

    return dependency
