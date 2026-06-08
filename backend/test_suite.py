#!/usr/bin/env python3
"""LGIAP Automated Quality Tests — runs after every deploy, catches bugs before you spot them"""
import sys, os, json, re, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import urllib.request
import psycopg2
from app.config import DATABASE_URL

FAIL = 0; PASS = 0
def check(label, condition, detail=""):
    global FAIL, PASS
    if condition: PASS += 1; print(f"  ✅ {label}")
    else: FAIL += 1; print(f"  ❌ {label} — {detail}")

print("=" * 60)
print("🧪 LGIAP Automated Test Suite")
print("=" * 60)

# ─── FETCH ALL PAGES FIRST ───
def get(url):
    try:
        r = urllib.request.urlopen(f"http://localhost:8085{url}", timeout=10)
        return r.status, r.read().decode()
    except Exception as e:
        return -1, str(e)

_, dash = get("/")
_, dash_test = get("/?group=Test")
_, control = get("/control")

# ─── 1. DATABASE ───
print("\n📦 DATABASE INTEGRITY")
conn = psycopg2.connect(DATABASE_URL)
c = conn.cursor()

c.execute("SELECT count(*) FROM messages WHERE group_id IS NOT NULL AND group_name = group_id")
check("No group_name equals raw group_id", c.fetchone()[0] == 0, "group_name should not be raw group_id; NULL is acceptable for join events")

c.execute("SELECT count(*) FROM messages WHERE message_type IN ('file','image','video','audio') AND content_url IS NULL")
check("All media types have content_url", c.fetchone()[0] == 0)

c.execute("SELECT count(DISTINCT m.user_id) FROM messages m LEFT JOIN profiles p ON m.user_id=p.user_id WHERE p.user_id IS NULL AND m.user_id IS NOT NULL AND m.message_type NOT IN ('join','member_joined','member_left','unsend')")
check("All message users have profiles", c.fetchone()[0] == 0)

c.execute("SELECT id, text_content FROM messages WHERE message_type='file' AND (text_content ILIKE '%%.bin' OR content_url ILIKE '%%.bin')")
bad_bin = c.fetchall()
check("No .bin file entries in DB", len(bad_bin) == 0, str(bad_bin[:3]))

conn.close()

# ─── 2. FILE SYSTEM ───
print("\n📁 FILE SYSTEM")
bin_files = subprocess.run("find /data/lgiap/media -name '*.bin' -type f 2>/dev/null | wc -l", shell=True, capture_output=True, text=True).stdout.strip()
check("No .bin files on disk", bin_files == "0", f"Found {bin_files} .bin files")

# ─── 3. API ───
print("\n🌐 API ENDPOINTS")
for path, label in [("/health","Health"), ("/","Dashboard"), ("/?group=Test","Filter by group"), ("/?relevance=useful","Useful filter"), ("/control","Control Center")]:
    s, _ = get(path)
    check(f"GET {label} → 200", s == 200, f"Got {s}")

s, thread = get("/api/thread/1")
check("GET /api/thread/1 → 200", s == 200, f"Got {s}")

# ─── 4. DASHBOARD HTML ───
print("\n🎨 DASHBOARD HTML QUALITY")

# 4a. Top bar layout
check("Top bar navigation present", "topbar" in dash and "top-controls" in dash)

# 4b. Mobile responsive
check("Mobile CSS breakpoints", "@media" in dash and "max-width" in dash)

# 4c. Column shrink
check("Column shrink buttons", "col-btn" in dash and "classList.toggle" in dash)

# 4d. No raw group IDs leaked
check("No raw group IDs in HTML", "C50f225918dcf6f294ab351fabd296f7c" not in dash)

# 4e. Drive links on own line (not clipped)
drive_links = len(re.findall(r'class="drive-link"', dash))
drive_breaks = len(re.findall(r'<br><a[^>]*class="drive-link"', dash))
check("Drive links on own line (<br>)", drive_breaks >= drive_links - 2, f"{drive_breaks}/{drive_links} have <br>")

# 4f. Profile pictures render
check("Profile avatars present", 'class="u-avatar"' in dash or 'class="u-fallback"' in dash)

# 4g. No empty/broken image src
check("No broken images", 'src=""' not in dash and 'src="None"' not in dash)

# 4h. All messages with content_url show Drive link
import re
# Find all data-col="6" cells (text column) that should have content
text_cols = re.findall(r'<td class="text-col"[^>]*>(.*?)</td>', dash, re.DOTALL)
drive_in_text = sum(1 for t in text_cols if 'drive-link' in t)
check("Text column cells have Drive links where expected", drive_in_text > 0, f"{drive_in_text} cells have drive links")

# 4i. Thread dropdown present
check("Thread dropdown in HTML", "threads-dropdown" in dash)

# 4j. Control center loads properly
check("Control center has table-wrap", "table-wrap" in control)
check("Control center has mobile CSS", "@media" in control and "max-width:600" in control)
check("Control center fetches live data", "fetch('/api/sysinfo')" in control or "api/sysinfo" in control)
check("Control center has auto-refresh", "setInterval(refresh" in control)

# ─── 5. PROCESSES ───
print("\n⚙️ PROCESSES")
try:
    pm2 = json.loads(subprocess.run("pm2 jlist 2>/dev/null", shell=True, capture_output=True, text=True).stdout)
    for name in ["lgiap-api", "lgiap-worker"]:
        proc = [p for p in pm2 if p.get('name') == name]
        online = len(proc) > 0 and proc[0].get('pm2_env',{}).get('status') == 'online'
        check(f"{name} running", online)
except:
    check("PM2 accessible", False)

# ─── SUMMARY ───
print("\n" + "=" * 60)
total = PASS + FAIL
pct = (PASS / total * 100) if total > 0 else 0
if FAIL == 0: emoji = "🟢 ALL CLEAN"
elif FAIL <= 2: emoji = f"🟡 {FAIL} WARNINGS"
else: emoji = f"🔴 {FAIL} FAILURES"
print(f"  {emoji}")
print(f"  {PASS}/{total} passed ({pct:.0f}%)")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
