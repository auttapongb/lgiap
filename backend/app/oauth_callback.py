"""LGIAP OAuth Callback — same-flow PKCE for Google Drive auth"""
import json, os, uuid
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import InstalledAppFlow

router = APIRouter()

OAUTH_CLIENT_PATH = "/data/lgiap/oauth_client.json"
OAUTH_TOKEN_PATH = "/data/lgiap/oauth_token.json"
REDIRECT = "https://lgiap.sasin.cfoth.ai/oauth-callback"

# Store flows by state so the callback gets the SAME flow (required for PKCE)
_pending_flows = {}

@router.get("/oauth-start")
async def oauth_start():
    """Generate auth URL with PKCE. Returns redirect to Google."""
    flow = InstalledAppFlow.from_client_secrets_file(
        OAUTH_CLIENT_PATH,
        scopes=["https://www.googleapis.com/auth/drive.file"],
        redirect_uri=REDIRECT
    )
    
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
    _pending_flows[state] = flow
    
    return RedirectResponse(auth_url)


@router.get("/oauth-callback", response_class=HTMLResponse)
async def oauth_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None)
):
    HEAD = '<html><body style="font-family:sans-serif;padding:2rem;text-align:center;background:#0f172a;color:#e2e8f0">'
    TAIL = '</body></html>'
    
    if error:
        return HTMLResponse(f"{HEAD}<h2 style='color:#ef4444'>Error: {error}</h2>{TAIL}")
    
    if not code:
        return HTMLResponse(f"{HEAD}<h2 style='color:#ef4444'>No code received</h2>{TAIL}")
    
    # Get the stored flow for this state (same PKCE verifier!)
    flow = _pending_flows.pop(state, None)
    if not flow:
        return HTMLResponse(
            f"{HEAD}<h2 style='color:#f59e0b'>State mismatch</h2>"
            f"<p>The authorization session expired. <a href='/oauth-start'>Try again</a></p>{TAIL}"
        )
    
    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        with open(OAUTH_TOKEN_PATH, "w") as f:
            json.dump({
                "refresh_token": creds.refresh_token,
                "token": creds.token,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
            }, f)
        os.chmod(OAUTH_TOKEN_PATH, 0o600)
        
        return HTMLResponse(
            f"{HEAD}<h2 style='color:#4ade80'>Authorized!</h2>"
            f"<p>Google Drive upload is now active.</p>"
            f"<p style='color:#94a3b8;font-size:.8rem'>You can close this window.</p>{TAIL}"
        )
        
    except Exception as e:
        return HTMLResponse(
            f"{HEAD}<h2 style='color:#ef4444'>Auth Failed</h2>"
            f"<p style='font-size:.8rem'>{str(e)[:200]}</p>{TAIL}"
        )
