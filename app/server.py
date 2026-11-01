import asyncio
from contextlib import asynccontextmanager
import datetime
import json
from collections import defaultdict
import os
import time
import tempfile
import zipfile
from typing import Optional, List, Dict, Any

from fastapi import Request, FastAPI, HTTPException, Depends, Header, Cookie, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from pydantic import BaseModel

from .config import config
from .network import network_info, validate_server_url
from .api_keys import api_keys
from .pool import pool_manager, match_pool_slot
from .manager import account_manager
from .passwords import password_manager, generate_secure_password

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

@asynccontextmanager
async def lifespan(app):
    await account_manager.startup()
    try:
        yield
    finally:
        await account_manager.shutdown()


app = FastAPI(title="iCloud HME Manager", version="3.1.0", lifespan=lifespan)

# Extension requests use explicit API keys; browser dashboard mutations must be same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"chrome-extension://[a-p]{32}",
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)


@app.middleware("http")
async def check_browser_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
        same_origin = origin == str(request.base_url).rstrip("/")
        extension = origin.startswith("chrome-extension://") and (
            request.headers.get("x-api-key") or request.headers.get("authorization"))
        if not same_origin and not extension:
            return Response(status_code=403, content="Cross-origin request rejected")
    return await call_next(request)


_login_attempts = defaultdict(list)

# --------------------------------------------------------------------- Auth Guards
async def require_dashboard_auth(
    authorization: Optional[str] = Header(None),
    ihme_session: Optional[str] = Cookie(None),
):
    token = None
    if authorization and authorization.startswith("Bearer "):
        cand = authorization.split("Bearer ", 1)[1].strip()
        token = cand
    elif ihme_session:
        token = ihme_session

    if not config.verify_session(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please log in.",
        )
    return True


async def require_extension_or_dashboard_auth(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    ihme_session: Optional[str] = Cookie(None),
):
    # Check explicit X-API-Key header
    key_candidate = x_api_key
    if key_candidate is not None:
        if api_keys.validate_key(key_candidate):
            return "api_key"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
        )

    # Check Bearer ihme_live_...
    tok = None
    if authorization and authorization.startswith("Bearer "):
        candidate = authorization.split("Bearer ", 1)[1].strip()
        if candidate.startswith("ihme_live_"):
            if api_keys.validate_key(candidate):
                return "api_key"
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked API key.",
            )
        tok = candidate
    elif ihme_session:
        tok = ihme_session

    if tok and config.verify_session(tok):
        return "session"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid API key or auth token.",
    )


# --------------------------------------------------------------------- Models
class SetupBody(BaseModel):
    password: str


class OnboardingBody(BaseModel):
    server_url: str
    complete: bool = False


class LoginBody(BaseModel):
    password: str


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


class CookiesBody(BaseModel):
    cookie: str
    proxy: Optional[str] = None


class GenerateBody(BaseModel):
    count: int
    label: Optional[str] = None


class DeleteBody(BaseModel):
    anonymousIds: List[str]
    mode: str = "both"  # both | deactivate | delete


class UpdateLabelBody(BaseModel):
    anonymousId: str
    label: str
    note: Optional[str] = ""


class DetailsBody(BaseModel):
    anonymousId: str


class ClaimBody(BaseModel):
    label: str
    note: Optional[str] = ""


class CreateKeyBody(BaseModel):
    name: str


class TlgActionBody(BaseModel):
    action: str  # generate | rename | inactive | active | delete | password
    name: Optional[str] = None
    label: Optional[str] = None
    new_name: Optional[str] = None
    email: Optional[str] = None
    mail: Optional[str] = None
    id: Optional[str] = None
    note: Optional[str] = None
    password: Optional[str] = None
    site: Optional[str] = None
    domain: Optional[str] = None


class PasswordSetBody(BaseModel):
    email: str
    password: str
    anonymousId: Optional[str] = ""
    site: Optional[str] = ""
    label: Optional[str] = ""


class PasswordGenBody(BaseModel):
    email: Optional[str] = None
    anonymousId: Optional[str] = ""
    site: Optional[str] = ""
    label: Optional[str] = ""
    length: Optional[int] = 18


class ExtensionPasswordBody(BaseModel):
    domain: Optional[str] = None
    email: Optional[str] = None
    action: Optional[str] = "get_or_create"  # check | get_or_create | generate_new | use_existing
    password: Optional[str] = None


# --------------------------------------------------------------------- Auth APIs
@app.get("/api/auth/status")
async def auth_status(
    authorization: Optional[str] = Header(None),
    ihme_session: Optional[str] = Cookie(None),
):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
    elif ihme_session:
        token = ihme_session

    authenticated = config.verify_session(token)
    return {
        "initialized": config.is_initialized(),
        "authenticated": authenticated,
        "has_cookies": bool(account_manager.client.cookies) if authenticated else False,
        "is_connected": account_manager.is_connected if authenticated else False,
        "onboarding_complete": bool(config.data.get("onboarding_complete") or account_manager.is_connected) if authenticated else False,
    }


@app.post("/api/auth/setup")
async def auth_setup(body: SetupBody, response: Response, request: Request):
    if config.is_initialized():
        raise HTTPException(400, "Master password has already been set.")
    if len(body.password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters.")

    config.set_password(body.password)
    token = config.create_session()
    response.set_cookie(
        key="ihme_session",
        value=token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return {"success": True, "token": token}


@app.post("/api/auth/login")
async def auth_login(body: LoginBody, response: Response, request: Request):
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    _login_attempts[client] = [t for t in _login_attempts[client] if now - t < 60]
    if len(_login_attempts[client]) >= 5:
        raise HTTPException(429, "Too many attempts. Try again in one minute.")
    _login_attempts[client].append(now)
    if not config.is_initialized():
        raise HTTPException(400, "System not initialized. Please set a master password first.")
    if not config.verify_password(body.password):
        raise HTTPException(401, "Incorrect password.")

    token = config.create_session()
    response.set_cookie(
        key="ihme_session",
        value=token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return {"success": True, "token": token}


@app.post("/api/auth/logout")
async def auth_logout(
    response: Response,
    ihme_session: Optional[str] = Cookie(None),
):
    if ihme_session:
        config.revoke_session(ihme_session)
    response.delete_cookie("ihme_session")
    return {"success": True}


@app.post("/api/auth/change-password", dependencies=[Depends(require_dashboard_auth)])
async def change_password(body: ChangePasswordBody):
    if len(body.new_password) < 4:
        raise HTTPException(400, "New password must be at least 4 characters.")
    if not config.verify_password(body.old_password):
        raise HTTPException(400, "Current password is incorrect.")
    config.set_password(body.new_password)
    config._active_sessions.clear()
    account_manager._log("password_change", "Master password was updated")
    return {"success": True, "message": "Password changed successfully."}


# --------------------------------------------------------------------- Account & Cookies
@app.get("/api/account", dependencies=[Depends(require_dashboard_auth)])
async def get_account():
    return account_manager.public_state()


@app.post("/api/account/cookies", dependencies=[Depends(require_dashboard_auth)])
async def update_cookies(body: CookiesBody):
    if not body.cookie.strip():
        raise HTTPException(400, "Cookie string cannot be empty.")
    await account_manager.set_new_cookies(body.cookie, body.proxy)
    await account_manager.refresh()
    pool_manager.wake_replenish()
    return account_manager.public_state()


@app.post("/api/account/refresh", dependencies=[Depends(require_dashboard_auth)])
async def refresh_account():
    await account_manager.refresh()
    return account_manager.public_state()


# --------------------------------------------------------------------- Emails Management
@app.get("/api/emails", dependencies=[Depends(require_dashboard_auth)])
async def list_emails():
    enriched = []
    for e in account_manager.emails:
        item = dict(e)
        pwd_entry = password_manager.get_password(e.get("hme", "")) or password_manager.get_password(e.get("anonymousId", ""))
        item["password"] = pwd_entry.get("password") if pwd_entry else None
        enriched.append(item)
    return {
        "state": account_manager.public_state(),
        "emails": enriched,
    }


# --------------------------------------------------------------------- Password Management
@app.get("/api/passwords", dependencies=[Depends(require_dashboard_auth)])
async def list_passwords():
    return password_manager.list_all()


@app.get("/api/passwords/{email_or_id}", dependencies=[Depends(require_dashboard_auth)])
async def get_password_endpoint(email_or_id: str):
    entry = password_manager.get_password(email_or_id)
    if not entry:
        raise HTTPException(404, "No password associated with this address.")
    return entry


@app.post("/api/passwords/set", dependencies=[Depends(require_dashboard_auth)])
async def set_password_endpoint(body: PasswordSetBody):
    if not body.email or not body.password:
        raise HTTPException(400, "Email and password are required.")
    entry = password_manager.set_password(
        email=body.email,
        password=body.password,
        anonymous_id=body.anonymousId or "",
        site=body.site or "",
        label=body.label or "",
    )
    account_manager._log("password_set", f"{body.email}")
    return {"ok": True, "entry": entry}


@app.post("/api/passwords/generate", dependencies=[Depends(require_dashboard_auth)])
async def generate_password_endpoint(body: PasswordGenBody):
    if body.email:
        entry = password_manager.generate_and_set(
            email=body.email,
            anonymous_id=body.anonymousId or "",
            site=body.site or "",
            label=body.label or "",
            length=body.length or 18,
        )
        account_manager._log("password_gen", f"{body.email}")
        return {"ok": True, "entry": entry, "password": entry.get("password")}
    else:
        pwd = generate_secure_password(body.length or 18)
        return {"ok": True, "password": pwd}


@app.delete("/api/passwords/{email_or_id}", dependencies=[Depends(require_dashboard_auth)])
async def delete_password_endpoint(email_or_id: str):
    ok = password_manager.delete_password(email_or_id)
    return {"ok": ok}


@app.post("/api/extension/password", dependencies=[Depends(require_extension_or_dashboard_auth)])
async def extension_password_endpoint(body: ExtensionPasswordBody):
    domain = (body.domain or "").strip()
    email_in = (body.email or "").strip()
    act = (body.action or "get_or_create").strip().lower()

    # 1. Look for existing password explicitly for this email or domain
    existing_pwd = None
    if email_in:
        existing_pwd = password_manager.get_password(email_in)
    elif domain:
        existing_pwd = password_manager.get_password_by_site(domain)

    # 2. Determine target email for new generation if needed
    target_email = email_in
    if not target_email and existing_pwd:
        target_email = existing_pwd.get("email", "")
    if not target_email and domain:
        for e in account_manager.emails:
            lbl = (e.get("label") or "").lower()
            if domain.lower() in lbl or lbl in domain.lower():
                target_email = e.get("hme", "")
                break
    if not target_email:
        target_email = password_manager.last_assigned_email or ""
        if not target_email and account_manager.emails:
            for e in account_manager.emails:
                if match_pool_slot(e.get("label", "")) is None:
                    target_email = e.get("hme", "")
                    break

    # 1. Action: check
    if act == "check":
        if existing_pwd:
            now = time.time()
            # If created or updated within last 5 seconds, it was just generated (duplicate request prevention)
            if (now - existing_pwd.get("created_at", 0) < 5.0) or (now - existing_pwd.get("updated_at", 0) < 5.0):
                return {
                    "ok": True,
                    "has_password": False,
                    "just_generated": True,
                    "email": existing_pwd.get("email", target_email),
                    "password": existing_pwd.get("password"),
                    "site": existing_pwd.get("site", domain),
                }
            return {
                "ok": True,
                "has_password": True,
                "email": existing_pwd.get("email", target_email),
                "password": existing_pwd.get("password"),
                "site": existing_pwd.get("site", domain),
            }
        return {
            "ok": True,
            "has_password": False,
            "email": target_email or None,
            "password": None,
            "site": domain,
        }

    # 2. Action: generate_new or get_or_create without existing
    if act == "generate_new" or (act == "get_or_create" and not existing_pwd):
        if not target_email:
            raise HTTPException(400, "No email address available to associate password with.")
        found = next((e for e in account_manager.emails if e.get("hme", "").lower() == target_email.lower()), None)
        anon_id = found.get("anonymousId", "") if found else ""
        lbl = found.get("label", "") if found else domain
        entry = password_manager.generate_and_set(
            email=target_email,
            anonymous_id=anon_id,
            site=domain,
            label=lbl,
        )
        account_manager._log("password_gen_ext", f"{target_email} ({domain})")
        return {
            "ok": True,
            "generated": True,
            "email": target_email,
            "password": entry.get("password"),
            "site": domain,
        }

    # 3. Action: use_existing or get_or_create with existing
    if existing_pwd:
        return {
            "ok": True,
            "generated": False,
            "email": existing_pwd.get("email", target_email),
            "password": existing_pwd.get("password"),
            "site": existing_pwd.get("site", domain),
        }

    raise HTTPException(400, "Unable to resolve or generate password.")


@app.post("/api/emails/generate", dependencies=[Depends(require_dashboard_auth)])
async def manual_generate(body: GenerateBody):
    if body.count < 1 or body.count > 50:
        raise HTTPException(400, "Quantity must be between 1 and 50.")
    try:
        await account_manager.start_manual_generation(body.count, body.label)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return account_manager.public_state()


@app.post("/api/emails/generate/stop", dependencies=[Depends(require_dashboard_auth)])
async def stop_manual_generate():
    await account_manager.stop_manual_generation()
    return account_manager.public_state()


@app.post("/api/emails/delete", dependencies=[Depends(require_extension_or_dashboard_auth)])
async def delete_emails(body: DeleteBody):
    if not body.anonymousIds:
        raise HTTPException(400, "No address selected.")
    res = await account_manager.delete_emails(body.anonymousIds, body.mode)
    if res.get("failed", 0) > 0 and res.get("success", 0) == 0:
        err_msg = ", ".join(res.get("errors", [])) or "iCloud error during deletion."
        raise HTTPException(400, err_msg)
    return {"result": res, "state": account_manager.public_state()}


@app.post("/api/emails/update-label", dependencies=[Depends(require_dashboard_auth)])
async def update_label(body: UpdateLabelBody):
    """Calls iCloud updateMetaData to rename an email."""
    if not body.anonymousId:
        raise HTTPException(400, "anonymousId is required.")
    res = await account_manager.update_email_metadata(
        body.anonymousId, body.label, body.note or ""
    )
    if res and res.get("error"):
        raise HTTPException(400, res.get("reason") or "iCloud error during renaming.")
    return {"success": True, "result": res}


@app.post("/api/emails/details", dependencies=[Depends(require_dashboard_auth)])
async def get_email_details(body: DetailsBody):
    """Calls iCloud get endpoint for full details."""
    if not body.anonymousId:
        raise HTTPException(400, "anonymousId is required.")
    res = await account_manager.get_email_details(body.anonymousId)
    return res


# --------------------------------------------------------------------- Pool (Reserve)
@app.get("/api/pool", dependencies=[Depends(require_dashboard_auth)])
async def get_pool():
    return pool_manager.public_state(account_manager.emails)


@app.post("/api/pool/claim", dependencies=[Depends(require_dashboard_auth)])
async def claim_pool_email(body: ClaimBody):
    """Claims an email from pool directly from web dashboard."""
    res = await pool_manager.claim_email(
        account_manager.client, body.label, body.note or "", log_func=account_manager._log
    )
    if not res.get("success"):
        raise HTTPException(429, res.get("message", "Error claiming email from pool."))
    asyncio.create_task(account_manager.refresh())
    return res


@app.post("/api/pool/replenish", dependencies=[Depends(require_dashboard_auth)])
async def trigger_replenish():
    pool_manager.wake_replenish()
    return pool_manager.public_state(account_manager.emails)


# --------------------------------------------------------------------- API Keys
@app.get("/api/keys", dependencies=[Depends(require_dashboard_auth)])
async def get_keys():
    return api_keys.list_keys()


@app.post("/api/keys", dependencies=[Depends(require_dashboard_auth)])
async def create_key(body: CreateKeyBody):
    return api_keys.create_key(body.name)


@app.delete("/api/keys/{key_id}", dependencies=[Depends(require_dashboard_auth)])
async def delete_key(key_id: str):
    if not api_keys.delete_key(key_id):
        raise HTTPException(404, "API key not found.")
    return {"success": True}


# --------------------------------------------------------------------- Extension APIs
@app.get("/api/extension/status", dependencies=[Depends(require_extension_or_dashboard_auth)])
async def extension_status():
    pool_state = pool_manager.public_state()
    active_count = len([e for e in account_manager.emails if match_pool_slot(e.get("label", "")) is None and e.get("isActive", True)])
    return {
        "ok": True,
        "account": account_manager.forward_email,
        "is_connected": account_manager.is_connected,
        "pool_ready": pool_state["ready_count"],
        "pool_target": pool_state["target"],
        "pool_status": pool_state["status"],
        "pool_message": pool_state["message"],
        "total_emails": active_count,
    }


@app.post("/api/extension/claim", dependencies=[Depends(require_extension_or_dashboard_auth)])
async def extension_claim(body: ClaimBody):
    """Endpoint called by Chrome extension popup: attributes instant email & renames it."""
    res = await pool_manager.claim_email(
        account_manager.client,
        body.label,
        body.note or "Assigned via Chrome Extension",
        log_func=account_manager._log,
    )
    if not res.get("success"):
        # Return HTTP 429 for rate limit / pool depletion
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=res.get("message", "Reserve pool temporarily empty or rate limit reached."),
        )
    asyncio.create_task(account_manager.refresh())
    return res


@app.get("/api/extension/recent", dependencies=[Depends(require_extension_or_dashboard_auth)])
async def extension_recent():
    return pool_manager.claimed[-10:]


@app.get("/api/extension/emails", dependencies=[Depends(require_extension_or_dashboard_auth)])
async def extension_emails():
    """Returns all active iCloud Hide-My-Email addresses instantly from RAM cache, excluding pool reserve and inactive addresses."""
    valid_emails = [
        {
            "anonymousId": e.get("anonymousId"),
            "label": e.get("label", ""),
            "hme": e.get("hme", ""),
            "isActive": e.get("isActive", True),
            "created_at": e.get("createTimestamp", 0) / 1000.0 if e.get("createTimestamp") else 0,
        }
        for e in account_manager.emails
        if match_pool_slot(e.get("label", "")) is None and e.get("isActive", True)
    ]
    return {
        "ok": True,
        "count": len(valid_emails),
        "emails": valid_emails,
    }


def _format_date(ts: Optional[int]) -> str:
    if not ts:
        return ""
    try:
        sec = ts / 1000.0 if ts > 10_000_000_000 else float(ts)
        return datetime.datetime.fromtimestamp(sec).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


@app.get("/tlg", dependencies=[Depends(require_extension_or_dashboard_auth)])
@app.get("/api/tlg", dependencies=[Depends(require_extension_or_dashboard_auth)])
async def get_tlg_emails():
    """Optimized endpoint for Telegram Bot.
    Returns complete list of all iCloud Hide-My-Email addresses
    (both active and inactive, excluding pool reserve addresses) with:
    id, name, email, status, creation_date, and timestamp.
    """
    tlg_emails = []
    for e in account_manager.emails:
        if match_pool_slot(e.get("label", "")) is not None:
            continue
        pwd_entry = password_manager.get_password(e.get("hme", "")) or password_manager.get_password(e.get("anonymousId", ""))
        pwd_val = pwd_entry.get("password") if pwd_entry else None
        tlg_emails.append({
            "id": e.get("anonymousId", ""),
            "name": e.get("label", "") or "Unnamed",
            "email": e.get("hme", ""),
            "mail": e.get("hme", ""),
            "status": "active" if e.get("isActive", True) else "inactive",
            "creation_date": _format_date(e.get("createTimestamp")),
            "creation": _format_date(e.get("createTimestamp")),
            "created_at_timestamp": (e.get("createTimestamp") / 1000.0) if e.get("createTimestamp") else 0,
            "password": pwd_val,
        })

    return {
        "ok": True,
        "count": len(tlg_emails),
        "emails": tlg_emails,
    }


@app.post("/tlg", dependencies=[Depends(require_extension_or_dashboard_auth)])
@app.post("/api/tlg", dependencies=[Depends(require_extension_or_dashboard_auth)])
async def post_tlg_action(body: TlgActionBody):
    """Processes bot actions for Telegram: generate, rename, inactive, active, delete, password.
    Matches GUI actions with immediate response.
    """
    action = (body.action or "").strip().lower()
    req_name = (body.new_name or body.name or body.label or "").strip()
    req_email = (body.email or body.mail or body.id or "").strip()

    if not action:
        raise HTTPException(400, "Field 'action' is required (generate, rename, inactive, active, delete, password).")

    # Helper to find email record by address or ID
    def _find_email(ident: str) -> Optional[Dict[str, Any]]:
        target = ident.strip().lower()
        for e in account_manager.emails:
            if e.get("hme", "").strip().lower() == target or e.get("anonymousId", "").strip().lower() == target:
                return e
        return None

    # Helper to build consistent response payload
    def _make_email_obj(e: Dict[str, Any], override_name: Optional[str] = None, override_status: Optional[str] = None) -> Dict[str, Any]:
        st = override_status if override_status is not None else ("active" if e.get("isActive", True) else "inactive")
        lbl = override_name if override_name is not None else (e.get("label", "") or "Unnamed")
        created_str = _format_date(e.get("createTimestamp"))
        created_ts = (e.get("createTimestamp") / 1000.0) if e.get("createTimestamp") else time.time()
        pwd_entry = password_manager.get_password(e.get("hme", "")) or password_manager.get_password(e.get("anonymousId", ""))
        pwd_val = pwd_entry.get("password") if pwd_entry else None
        return {
            "id": e.get("anonymousId", ""),
            "name": lbl,
            "email": e.get("hme", ""),
            "mail": e.get("hme", ""),
            "status": st,
            "creation": created_str,
            "creation_date": created_str,
            "created_at_timestamp": created_ts,
            "password": pwd_val,
        }

    # 1. ACTION: GENERATE
    if action == "generate":
        use_name = req_name or "Telegram Bot"
        try:
            res = await account_manager.create_new_email(
                label=use_name,
                note=body.note or "Created via Telegram Bot",
            )
        except ValueError as e:
            err_str = str(e)
            if "limit" in err_str.lower() or "quota" in err_str.lower():
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, err_str)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, err_str)
        except Exception as e:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))

        asyncio.create_task(account_manager.refresh())

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        email_data = {
            "id": res.get("anonymousId", ""),
            "name": res.get("label", use_name),
            "email": res.get("email", ""),
            "mail": res.get("email", ""),
            "status": "active",
            "creation": now_str,
            "creation_date": now_str,
            "created_at_timestamp": res.get("created_at", time.time()),
        }
        return {
            "ok": True,
            "success": True,
            "action": "generate",
            "email": email_data,
            "name": email_data["name"],
            "mail": email_data["mail"],
            "creation": email_data["creation"],
            "status": email_data["status"],
        }

    # 2. ACTION: RENAME
    elif action == "rename":
        if not req_email:
            raise HTTPException(400, "Field 'email' (or 'id') is required to rename an address.")
        if not req_name:
            raise HTTPException(400, "Field 'name' (or 'new_name') is required for renaming.")

        found = _find_email(req_email)
        if not found:
            raise HTTPException(404, f"Address '{req_email}' not found.")

        anon_id = found.get("anonymousId", "")
        update_res = await account_manager.update_email_metadata(
            anon_id, req_name, body.note or found.get("note", "")
        )
        if update_res and update_res.get("error"):
            err_msg = update_res.get("reason") or str(update_res.get("error"))
            raise HTTPException(400, f"iCloud rename error: {err_msg}")

        email_data = _make_email_obj(found, override_name=req_name)
        return {
            "ok": True,
            "success": True,
            "action": "rename",
            "email": email_data,
            "name": email_data["name"],
            "mail": email_data["mail"],
            "creation": email_data["creation"],
            "status": email_data["status"],
        }

    # 3. ACTION: INACTIVE / DEACTIVATE
    elif action in ("inactive", "deactivate"):
        if not req_email:
            raise HTTPException(400, "Field 'email' (or 'id') is required.")

        found = _find_email(req_email)
        if not found:
            raise HTTPException(404, f"Address '{req_email}' not found.")

        anon_id = found.get("anonymousId", "")
        del_res = await account_manager.delete_emails([anon_id], mode="deactivate")
        if del_res.get("failed", 0) > 0 and del_res.get("success", 0) == 0:
            err_msg = ", ".join(del_res.get("errors", [])) or "iCloud error during deactivation."
            raise HTTPException(400, err_msg)

        email_data = _make_email_obj(found, override_status="inactive")
        return {
            "ok": True,
            "success": True,
            "action": "inactive",
            "email": email_data,
            "name": email_data["name"],
            "mail": email_data["mail"],
            "creation": email_data["creation"],
            "status": email_data["status"],
        }

    # 4. ACTION: ACTIVE / REACTIVATE
    elif action in ("active", "activate", "reactivate"):
        if not req_email:
            raise HTTPException(400, "Field 'email' (or 'id') is required.")

        found = _find_email(req_email)
        if not found:
            raise HTTPException(404, f"Address '{req_email}' not found.")

        anon_id = found.get("anonymousId", "")
        del_res = await account_manager.delete_emails([anon_id], mode="activate")
        if del_res.get("failed", 0) > 0 and del_res.get("success", 0) == 0:
            err_msg = ", ".join(del_res.get("errors", [])) or "iCloud error during reactivation."
            raise HTTPException(400, err_msg)

        email_data = _make_email_obj(found, override_status="active")
        return {
            "ok": True,
            "success": True,
            "action": "active",
            "email": email_data,
            "name": email_data["name"],
            "mail": email_data["mail"],
            "creation": email_data["creation"],
            "status": email_data["status"],
        }

    # 5. ACTION: DELETE
    elif action in ("delete", "remove"):
        if not req_email:
            raise HTTPException(400, "Field 'email' (or 'id') is required for deletion.")

        found = _find_email(req_email)
        if not found:
            raise HTTPException(404, f"Address '{req_email}' not found.")

        anon_id = found.get("anonymousId", "")
        addr = found.get("hme", req_email)
        del_res = await account_manager.delete_emails([anon_id], mode="both")
        if del_res.get("failed", 0) > 0 and del_res.get("success", 0) == 0:
            err_msg = ", ".join(del_res.get("errors", [])) or "iCloud error during deletion."
            raise HTTPException(400, err_msg)

        return {
            "ok": True,
            "success": True,
            "action": "delete",
            "message": f"Address {addr} permanently deleted.",
            "deleted_email": addr,
            "id": anon_id,
        }

    # 6. ACTION: PASSWORD (Set or Generate Password)
    elif action in ("password", "pass", "gen_password", "set_password"):
        target_ident = req_email
        if not target_ident:
            target_ident = password_manager.last_assigned_email or ""
            if not target_ident and account_manager.emails:
                for e in account_manager.emails:
                    if match_pool_slot(e.get("label", "")) is None:
                        target_ident = e.get("hme", "")
                        break

        if not target_ident:
            raise HTTPException(400, "Field 'email' (or 'id') is required to set or generate a password.")

        found = _find_email(target_ident)
        email_addr = found.get("hme", "") if found else target_ident
        anon_id = found.get("anonymousId", "") if found else ""
        lbl = found.get("label", "") if found else (req_name or "Unknown")

        req_pwd = (body.password or "").strip()
        site_val = (body.site or body.domain or lbl or "").strip()

        if req_pwd:
            entry = password_manager.set_password(
                email=email_addr,
                password=req_pwd,
                anonymous_id=anon_id,
                site=site_val,
                label=lbl,
            )
            was_generated = False
        else:
            entry = password_manager.generate_and_set(
                email=email_addr,
                anonymous_id=anon_id,
                site=site_val,
                label=lbl,
            )
            was_generated = True

        account_manager._log("password_set", f"{email_addr} ({lbl})")

        email_data = _make_email_obj(found) if found else {
            "id": anon_id,
            "name": lbl,
            "email": email_addr,
            "mail": email_addr,
            "status": "active",
            "creation": _format_date(time.time()),
            "creation_date": _format_date(time.time()),
            "created_at_timestamp": time.time(),
            "password": entry.get("password"),
        }
        email_data["password"] = entry.get("password")

        return {
            "ok": True,
            "success": True,
            "action": "password",
            "password": entry.get("password"),
            "password_generated": was_generated,
            "name": email_data["name"],
            "mail": email_data["mail"],
            "email": email_data,
            "creation": email_data["creation"],
            "status": email_data["status"],
        }

    else:
        raise HTTPException(
            400,
            f"Unknown action '{body.action}'. Supported actions: generate, rename, inactive, active, delete, password."
        )


@app.get("/api/extension/download", dependencies=[Depends(require_dashboard_auth)])
async def download_extension(request: Request):
    """Build a private-network extension package using the selected public-facing URL."""
    default_url = config.data.get("server_url") or str(request.base_url).rstrip("/")
    ext_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension")
    if not os.path.isfile(os.path.join(ext_dir, "manifest.json")):
        raise HTTPException(503, "Extension files are missing from this installation.")
    with tempfile.NamedTemporaryFile(prefix="ihme-extension-", suffix=".zip", delete=False) as archive:
        archive_path = archive.name
    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(ext_dir):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for file in files:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, ext_dir).replace(os.sep, "/")
                    with open(file_path, "rb") as f:
                        content = f.read()
                    if rel_path == "config.js":
                        content = ("const IHME_DEFAULT_SERVER_URL = " + json.dumps(default_url) + ";\n").encode()
                    zf.writestr(rel_path, content)
        return FileResponse(
            archive_path, media_type="application/zip", filename="icloud-hme-extension.zip",
            background=BackgroundTask(os.unlink, archive_path),
            headers={"Cache-Control": "no-store"},
        )
    except Exception:
        os.unlink(archive_path)
        raise


@app.get("/api/settings", dependencies=[Depends(require_dashboard_auth)])
async def get_settings():
    return {"settings": config.get_settings(), "proxy": account_manager.client.proxy or "",
            "network": network_info()}


@app.post("/api/settings", dependencies=[Depends(require_dashboard_auth)])
async def update_settings(body: OnboardingBody):
    try:
        url = validate_server_url(body.server_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Completing onboarding also permits exploring the dashboard before connecting iCloud.
    config.data["server_url"] = url
    config.data["onboarding_complete"] = body.complete or config.data.get("onboarding_complete", False)
    config.save()
    return config.get_settings()


@app.get("/api/logs", dependencies=[Depends(require_dashboard_auth)])
async def get_logs():
    return {"logs": account_manager.read_logs()}


# --------------------------------------------------------------------- UI Static Files
@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
