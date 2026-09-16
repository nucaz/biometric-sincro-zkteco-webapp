"""
Audit trail: who did what, and from which PC.

Honest limitation up front: a web browser cannot report its own Windows
computer name to a server -- that's not something any browser API exposes
(for good privacy reasons). What we *can* get is the client's IP address
(always) and, best-effort, a hostname via reverse DNS on that IP. On a
domain-joined network where DNS registration is on (the normal default for
AD-joined Windows PCs), that reverse lookup usually resolves to the actual
PC name. On a flat/unmanaged network, or from outside it, it will just
come back empty and the log falls back to showing the IP address alone.
"""
import socket
from flask import request

from .models import AuditLog

REVERSE_DNS_TIMEOUT = 0.7  # seconds -- never let a slow/broken DNS server stall a request


def resolve_hostname(ip):
    """Best-effort reverse DNS lookup of `ip`. Returns None (never raises)
    if it can't be resolved in time."""
    if not ip:
        return None
    previous_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(REVERSE_DNS_TIMEOUT)
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return None
    finally:
        socket.setdefaulttimeout(previous_timeout)


def client_ip():
    """The requester's IP. Honors X-Forwarded-For's first hop for the
    (documented, opt-in) case of running behind a reverse proxy -- see
    deploy/*/README.md for exposing this outside the LAN via nginx/IIS."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def client_user_agent():
    return request.headers.get("User-Agent", "")[:250]


def log_event(db, action, username=None, target=None, detail=None, ip=None, hostname=None, user_agent=None):
    """Append one row. Never raises on its own account (a logging bug
    should never take down the action it's trying to record) -- callers
    that need the write to definitely land should call db.commit()
    themselves right after."""
    try:
        if ip is None:
            ip = client_ip()
        if hostname is None:
            hostname = resolve_hostname(ip)
        if user_agent is None:
            user_agent = client_user_agent()
        db.add(AuditLog(
            username=username, action=action, target=target, detail=detail,
            ip_address=ip, hostname=hostname, user_agent=user_agent,
        ))
    except Exception as e:
        print(f"Warning: could not write audit log entry ({action}): {e}")
