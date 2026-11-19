import hmac
import ipaddress

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db

LOOPBACK_CLIENTS = {"testclient"}
PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip", "x-forwarded-host", "tailscale-user-login")


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host in LOOPBACK_CLIENTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def require_auth(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Access-control boundary.

    - If IOI_API_TOKEN is set, every API call must send `Authorization: Bearer <token>`.
    - If no token is configured, only loopback clients are allowed (local-only mode).
    """
    token = get_settings().api_token
    if token:
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if not supplied or not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="Missing or invalid API token", headers={"WWW-Authenticate": "Bearer"})
        return
    if not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(status_code=403, detail="No API token configured: only local (loopback) access is allowed")
    # A reverse proxy (Caddy, Nginx, Tailscale Serve…) connects from loopback on behalf of remote
    # users, so a forwarded request is never treated as local.
    if any(h in request.headers for h in PROXY_HEADERS):
        raise HTTPException(status_code=403, detail="Request came through a proxy: set IOI_API_TOKEN to allow remote access")


def actor(x_ioi_actor: str | None = Header(default=None)) -> str:
    return (x_ioi_actor or "owner").strip()[:100] or "owner"


class Paging:
    def __init__(self, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
        self.limit = limit
        self.offset = offset


def paginate(db: Session, stmt: Select, paging: Paging) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.limit(paging.limit).offset(paging.offset)).all()
    return list(items), total


DB = Depends(get_db)
