"""LGIAP OAuth Callback - same-flow PKCE for Google Drive, Calendar + Gmail auth"""
import json, os, uuid
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import InstalledAppFlow

router = APIRouter()

CLIENT = "/data/lgiap/oauth_client.json"
TOKEN_DRIVE = "/data/lgiap/oauth_token.json"
TOKEN_CAL = "/data/lgiap/oauth_calendar_token.json"
TOKEN_GMAIL = "/data/lgiap/oauth_gmail_token.json"
REDIRECT = "https://lgiap.sasin.cfoth.ai/oauth-callback"

_pending_flows = {}

def _start_flow(scopes, prefix):
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT, scopes=scopes, redirect_uri=REDIRECT)
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
    _pending_flows[prefix + state] = flow
    return RedirectResponse(auth_url)

@router.get("/oauth-start")
async def oauth_start():
    return _start_flow(["https://www.googleapis.com/auth/drive.file"], "")

@router.get("/oauth-start-calendar")
async def oauth_start_calendar():
    return _start_flow(["https://www.googleapis.com/auth/calendar"], "calendar:")

@router.get("/oauth-start-gmail")
async def oauth_start_gmail():
    return _start_flow(["https://www.googleapis.com/auth/gmail.readonly"], "gmail:")

@router.get("/oauth-callback", response_class=HTMLResponse)
async def oauth_callback(code: str = Query(None), state: str = Query(None), error: str = Query(None)):
    HEAD = '<html><body style="font-family:sans-serif;padding:2rem;text-align:center;background:#0f172a;color:#e2e8f0">'
    TAIL = '</body></html>'
    if error:
        return HTMLResponse(f"{HEAD}<h2 style='color:#ef4444'>Error: {error}</h2>{TAIL}")
    if not code:
        return HTMLResponse(f"{HEAD}<h2 style='color:#ef4444'>No code received</h2>{TAIL}")

    prefixes = {"gmail:": (TOKEN_GMAIL, "Gmail"), "calendar:": (TOKEN_CAL, "Calendar"), "": (TOKEN_DRIVE, "Drive")}
    flow = None
    token_path = scope_name = ""
    for prefix, (tp, sn) in prefixes.items():
        if prefix + state in _pending_flows:
            flow = _pending_flows.pop(prefix + state)
            token_path, scope_name = tp, sn
            break

    if not flow:
        return HTMLResponse(f"{HEAD}<h2 style='color:#f59e0b'>State mismatch</h2><p>Session expired. <a href='/oauth-start'>Try again</a></p>{TAIL}")

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        with open(token_path, "w") as f:
            json.dump({"refresh_token": creds.refresh_token, "token": creds.token,
                       "client_id": creds.client_id, "client_secret": creds.client_secret}, f)
        os.chmod(token_path, 0o600)
        return HTMLResponse(f"{HEAD}<h2 style='color:#4ade80'>Authorized!</h2><p>Google {scope_name} access is now active.</p><p style='color:#94a3b8;font-size:.8rem'>You can close this window.</p>{TAIL}")
    except Exception as e:
        return HTMLResponse(f"{HEAD}<h2 style='color:#ef4444'>Auth Failed</h2><p style='font-size:.8rem'>{str(e)[:200]}</p>{TAIL}")
