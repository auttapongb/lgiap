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
from fastapi.responses import HTMLResponse, JSONResponse
@app.get("/control", response_class=HTMLResponse)
async def control_center():
    import os as _os
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "dashboard.html")
    with open(path) as f:
        return f.read()

# ── System Info API ──
import subprocess, json, time as _time

@app.get("/api/sysinfo")
async def sysinfo():
    """Real-time system stats for the control center dashboard"""
    import psutil
    data = {"updated": _time.strftime("%Y-%m-%d %H:%M:%S"), "main": {}, "ginnie": {}, "pm2": [], "lgiap": {}}
    
    # Main VPS
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    data["main"] = {
        "ram_used_gb": round(mem.used / (1024**3), 1),
        "ram_total_gb": round(mem.total / (1024**3), 1),
        "ram_pct": mem.percent,
        "ram_free_gb": round(mem.available / (1024**3), 1),
        "disk_used_gb": round(disk.used / (1024**3)),
        "disk_total_gb": round(disk.total / (1024**3)),
        "disk_pct": disk.percent,
        "disk_free_gb": round(disk.free / (1024**3)),
        "cpu_cores": psutil.cpu_count(),
        "cpu_pct": round(psutil.cpu_percent(interval=0.5), 1),
        "hostname": os.uname().nodename,
    }
    
    # PM2 processes
    try:
        r = subprocess.run("pm2 jlist", shell=True, capture_output=True, text=True, timeout=5)
        for p in json.loads(r.stdout):
            mon = p.get("monit", {}) or {}
            env = p.get("pm2_env", {}) or {}
            data["pm2"].append({
                "name": p.get("name","?"), 
                "status": env.get("status","?"),
                "memory_mb": round(mon.get("memory",0) / (1024**2), 1),
                "cpu_pct": mon.get("cpu", 0),
                "restarts": env.get("restart_time", 0),
            })
    except: pass
    
    # Ginnie VPS
    try:
        ginnie = subprocess.run(
            ["ssh", "-i", "/root/.ssh/ginnie-recovery", "-o", "ConnectTimeout=5", 
             "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes", 
             "root@72.60.43.17", "python3 -c '"
             "import psutil,json,subprocess;"
             "m=psutil.virtual_memory();d=psutil.disk_usage(\"/\");"
             "r=subprocess.run(\"docker ps --format {{.Names}}|{{.Status}}\",shell=True,capture_output=True,text=True);"
             "containers=[{\"name\":l.split(\"|\")[0],\"status\":l.split(\"|\")[1] if \"|\" in l else l} for l in r.stdout.strip().split(chr(10)) if l];"
             "print(json.dumps({\"ram_used\":round(m.used/(1024**3),1),\"ram_total\":round(m.total/(1024**3),1),\"ram_pct\":m.percent,"
             "\"disk_used\":round(d.used/(1024**3)),\"disk_total\":round(d.total/(1024**3)),\"disk_pct\":d.percent,"
             "\"cpu_cores\":psutil.cpu_count(),\"containers\":containers}))'"
            ],
            capture_output=True, text=True, timeout=10
        )
        if ginnie.returncode == 0:
            data["ginnie"] = json.loads(ginnie.stdout.strip())
        else:
            data["ginnie"] = {"error": f"SSH exit {ginnie.returncode}"}
    except Exception as e:
        data["ginnie"] = {"error": str(e)[:100]}
    
    # LGIAP stats
    try:
        from app.config import DATABASE_URL
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM messages"); data["lgiap"]["msgs"] = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT group_id) FROM messages WHERE group_id IS NOT NULL"); data["lgiap"]["groups"] = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT user_id) FROM messages"); data["lgiap"]["users"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM messages WHERE ai_rating >= 2"); data["lgiap"]["useful"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM messages WHERE ai_rating = -1"); data["lgiap"]["pending"] = cur.fetchone()[0]
        conn.close()
    except: pass
    
    return data

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8085))
    uvicorn.run(app, host="0.0.0.0", port=port)
