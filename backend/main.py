#!/usr/bin/env python3
"""LGIAP Backend — FastAPI application entry point"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="LGIAP", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "lgiap-api"}

# Import webhook routes (register LINE handler)
from app.webhooks import router as webhook_router
app.include_router(webhook_router)

# Import dashboard API
from app.dashboard import router as dashboard_router
app.include_router(dashboard_router)

# Import thread detection API
from app.thread_api import router as thread_router
app.include_router(thread_router)

from app.oauth_callback import router as oauth_router
app.include_router(oauth_router)

# Serve control center dashboard
from fastapi.responses import HTMLResponse
@app.get("/control", response_class=HTMLResponse)
async def control_center():
    import os as _os
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "dashboard.html")
    with open(path) as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8085))
    uvicorn.run(app, host="0.0.0.0", port=port)
