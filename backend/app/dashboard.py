"""LGIAP Dashboard — Table view with real user profiles, filters, threads"""
import json, os
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import psycopg2
from app.config import DATABASE_URL

router = APIRouter()
MEDIA_ROOT = "/data/lgiap/media"

def _get_db():
    return psycopg2.connect(DATABASE_URL)

@router.get("/api/thread/{thread_id}")
async def get_thread(thread_id: int):
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, title, topic, message_count, started_at, last_message_at FROM conversation_threads WHERE id = %s", (thread_id,))
    thread = cur.fetchone()
    if not thread:
        conn.close()
        return JSONResponse({"error": "Thread not found"}, status_code=404)
    cur.execute("""
        SELECT m.id, m.user_id, m.message_type, m.text_content, m.timestamp, m.ai_rating, m.ai_topic, m.content_url,
               p.display_name, p.picture_url
        FROM messages m LEFT JOIN profiles p ON m.user_id = p.user_id
        WHERE m.thread_id = %s ORDER BY m.timestamp
    """, (thread_id,))
    messages = [{"id": m[0], "user": m[1], "name": m[8] or m[1][:12] if m[1] else "?", "pic": m[9] or "",
                 "type": m[2], "text": m[3], "time": str(m[4])[:19] if m[4] else "",
                 "rating": m[5], "topic": m[6], "content_url": m[7]} for m in cur.fetchall()]
    conn.close()
    return {"thread": {"id": thread[0], "title": thread[1], "topic": thread[2], "count": thread[3], "started": str(thread[4])[:19], "ended": str(thread[5])[:19]}, "messages": messages}

@router.get("/media/{path:path}")
async def serve_media(path: str):
    safe = os.path.normpath(path)
    if safe.startswith("..") or safe.startswith("/"): return JSONResponse({"error": "Invalid path"}, status_code=403)
    filepath = os.path.join(MEDIA_ROOT, safe)
    if not os.path.exists(filepath) or not os.path.isfile(filepath): return JSONResponse({"error": "File not found"}, status_code=404)
    return FileResponse(filepath)

@router.get("/", response_class=HTMLResponse)
async def dashboard(group: str = Query(None), relevance: str = Query(None)):
    conn = _get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT DISTINCT COALESCE(group_name, group_id) as dn, group_id FROM messages WHERE group_id IS NOT NULL ORDER BY dn")
    all_group_pairs = cur.fetchall()
    
    selected_group_id = None
    if group:
        for name, gid in all_group_pairs:
            if group == name or group == gid: selected_group_id = gid; break
    
    where = []
    params = []
    if selected_group_id: where.append("m.group_id = %s"); params.append(selected_group_id)
    if relevance == "useful": where.append("m.ai_rating >= 2")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    
    cur.execute(f"SELECT count(*) FROM messages m {where_sql}", params or None)
    total = cur.fetchone()[0]
    if selected_group_id: cur.execute("SELECT count(DISTINCT user_id) FROM messages WHERE group_id=%s", (selected_group_id,))
    else: cur.execute("SELECT count(DISTINCT user_id) FROM messages")
    users_cnt = cur.fetchone()[0]
    uf = "WHERE m.ai_rating >= 2"
    if selected_group_id: uf += " AND m.group_id=%s"; cur.execute(f"SELECT count(*) FROM messages m {uf}", (selected_group_id,))
    else: cur.execute(f"SELECT count(*) FROM messages m {uf}")
    useful_cnt = cur.fetchone()[0]
    cur.execute("SELECT count(DISTINCT group_id) FROM messages WHERE group_id IS NOT NULL")
    groups_cnt = cur.fetchone()[0]
    
    tw = f"WHERE group_id = '{selected_group_id}'" if selected_group_id else ""
    cur.execute(f"SELECT id, title, message_count, started_at FROM conversation_threads {tw} ORDER BY started_at DESC LIMIT 15")
    threads = cur.fetchall()
    
    query = f"""
        SELECT m.id, m.group_id, COALESCE(m.group_name, m.group_id), m.user_id, m.message_type,
               m.text_content, m.timestamp, m.ai_rating, m.ai_topic, m.thread_id, m.content_url,
               p.display_name, p.picture_url
        FROM messages m LEFT JOIN profiles p ON m.user_id = p.user_id
        {where_sql} ORDER BY m.timestamp ASC LIMIT 200
    """
    cur.execute(query, params or None)
    messages = cur.fetchall()
    conn.close()
    
    group_options = '<option value="">All Groups</option>'
    for gname, gid in all_group_pairs:
        sel = "selected" if (group and (group == gname or group == gid)) else ""
        group_options += f'<option value="{gname}" {sel}>{gname}</option>'
    rel_sel = "selected" if relevance == "useful" else ""
    
    rating_badge = {0: "⚫ social", 1: "⚪ logistics", 2: "🟡 useful", 3: "🔴 critical", -1: "⏳ pending"}
    type_icon = {"text":"💬","image":"🖼","video":"🎬","audio":"🎤","file":"📎","sticker":"😀","join":"👋","member_joined":"👤+","member_left":"👤-","unsend":"🗑"}
    
    thread_html = ""
    for t in threads:
        tid, title, cnt, started = t
        ts = str(started)[11:16] if started else ""
        thread_html += f'<div class="thread-item" onclick="openThread({tid})"><span class="ti-time">{ts}</span><span class="ti-title">{title[:40]}</span><span class="ti-count">{cnt}</span></div>'
    if not threads: thread_html = '<div class="empty">No threads yet</div>'
    
    msg_rows = ""
    for m in messages:
        mid, gid, gname, uid, mtype, text, ts, rating, topic, thread_id, content_url, display_name, pic_url = m
        
        name = display_name or (uid[:12] if uid else "-")
        avatar_html = f'<img src="{pic_url}" class="u-avatar" onerror="this.style.display=\'none\'">' if pic_url else f'<span class="u-fallback">{name[0].upper()}</span>'
        user_html = f'{avatar_html}<span class="u-name">{name}</span>'
        
        icon = type_icon.get(mtype, "📨")
        badge = rating_badge.get(rating, "⚪ unrated")
        time_str = str(ts)[11:19] if ts else ""
        date_str = str(ts)[:10] if ts else ""
        display_text = (text or f"[{mtype}]")[:150]
        topic_html = f'<span class="topic-tag">{topic}</span>' if topic else ""
        thread_attr = f'data-thread="{thread_id}"' if thread_id else ""
        
        media_html = ""
        if content_url and content_url.startswith("http"):
            drive_id = content_url.split("/d/")[-1].split("/")[0] if "/d/" in content_url else ""
            thumb = f"https://drive.google.com/thumbnail?id={drive_id}&sz=w120" if drive_id else ""
            icon_label = {"image":"🖼","video":"▶️","audio":"🎤","file":"📎"}.get(mtype, "📎")
            if mtype == "image" and thumb:
                media_html = f'<a href="{content_url}" target="_blank" onclick="event.stopPropagation()"><img src="{thumb}" class="msg-thumb" onerror="this.style.display=\'none\'"></a><br><a href="{content_url}" target="_blank" class="drive-link" onclick="event.stopPropagation()">{icon_label} View on Drive</a>'
            else:
                media_html = f'<a href="{content_url}" target="_blank" class="drive-link" onclick="event.stopPropagation()">{icon_label} View on Drive</a>'
        elif mtype == "image" and mid:
            safe_group = (gname or 'Default').replace('/', '_')[:50]
            media_html = f'<img src="/media/{safe_group}/images/{mid}_image.jpg" class="msg-thumb" loading="lazy" onclick="event.stopPropagation()" onerror="this.style.display=\'none\'">'
        elif mtype == "video" and mid:
            safe_group = (gname or 'Default').replace('/', '_')[:50]
            media_html = f'<a href="/media/{safe_group}/videos/{mid}_video.mp4" target="_blank" class="drive-link" onclick="event.stopPropagation()">▶️ Watch video</a>'
        
        msg_rows += f'''<tr class="msg-row" data-id="{mid}" {thread_attr} onclick="openThread({thread_id or 'null'})">
            <td class="time-col" data-col="0">{date_str}<br>{time_str}</td>
            <td class="icon-col" data-col="1">{icon}</td>
            <td class="user-col" data-col="2">{user_html}</td>
            <td class="type-col" data-col="3"><span class="type-badge">{mtype}</span></td>
            <td class="rating-col" data-col="4">{badge}{topic_html}</td>
            <td class="group-col" data-col="5" title="{gname}">{gname or gid[:12]}</td>
            <td class="text-col" data-col="6">{display_text}{media_html}</td>
        </tr>'''
    
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>LGIAP Archive</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,system-ui,sans-serif;background:#0f172a;color:#e2e8f0;display:flex;flex-direction:column;height:100vh;overflow:hidden;-webkit-text-size-adjust:100%}}

/* ── TOP NAV ── */
#topbar{{
  background:#1a2332;border-bottom:1px solid #334155;padding:.6rem 1rem;
  display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;
  flex-shrink:0;z-index:10;
}}
#topbar h2{{font-size:.85rem;color:#38bdf8;margin:0;white-space:nowrap;flex-shrink:0}}
.top-controls{{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;flex:1;min-width:0}}
.top-controls select,.top-controls button{{
  background:#0f172a;border:1px solid #334155;color:#e2e8f0;
  padding:.35rem .6rem;border-radius:6px;font-size:.72rem;cursor:pointer;
}}
.top-controls button{{background:#6366f1;border-color:#6366f1;white-space:nowrap}}
.top-controls button:hover{{background:#7c3aed}}

/* Stats row in topbar */
.top-stats{{display:flex;gap:.8rem;font-size:.68rem;color:#94a3b8;white-space:nowrap;align-items:center}}
.top-stats b{{color:#4ade80;font-weight:700}}

/* Mobile: stats hidden by default, toggle with .expanded */
#stats-toggle{{display:none;background:none;border:none;color:#38bdf8;font-size:.75rem;cursor:pointer;padding:.3rem .5rem}}

/* ── MAIN CONTENT ── */
#main{{flex:1;overflow-y:auto;overflow-x:auto;padding:.5rem 1rem;-webkit-overflow-scrolling:touch}}
table{{width:100%;border-collapse:collapse;font-size:.75rem;min-width:700px}}
th{{background:#1e293b;padding:.4rem .5rem;text-align:left;color:#94a3b8;position:sticky;top:0;z-index:1;cursor:pointer;user-select:none;transition:color .15s}}
th:hover{{color:#e2e8f0}}
th .col-hint{{font-size:.55rem;opacity:.4;margin-left:2px}}
th.shrunk{{color:#6366f1;font-size:.7rem}}
th.shrunk .col-hint{{opacity:1}}''
td{{padding:.3rem .5rem;border-bottom:1px solid #1e293b}}
td.shrunk{{padding:0;max-width:0;overflow:hidden;border-bottom-color:transparent}}
td.shrunk *{{display:none}}
td.shrunk .type-badge{{display:none}}
.msg-row{{cursor:pointer;transition:background .15s}}
.msg-row:hover{{background:rgba(99,102,241,.12)}}
.msg-row.highlight{{background:rgba(56,189,248,.15);border-left:3px solid #38bdf8}}
.time-col{{font-family:monospace;font-size:.62rem;color:#64748b;white-space:nowrap;width:68px}}
.icon-col{{width:24px;text-align:center;font-size:.8rem}}
.user-col{{color:#e2e8f0;font-size:.68rem;min-width:120px;white-space:nowrap}}
.u-avatar{{width:20px;height:20px;border-radius:50%;vertical-align:middle;margin-right:3px;object-fit:cover}}
.u-fallback{{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:50%;background:#6366f1;color:#fff;font-size:.6rem;font-weight:700;margin-right:3px;vertical-align:middle}}
.u-name{{vertical-align:middle}}
.type-col{{width:50px;text-align:center}}
.rating-col{{width:85px;font-size:.68rem;white-space:nowrap}}
.group-col{{color:#38bdf8;font-size:.68rem;width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.type-badge{{font-size:.58rem;background:#273449;padding:1px 4px;border-radius:3px;color:#64748b}}
.text-col{{max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.7rem}}
.msg-thumb{{max-width:70px;max-height:45px;border-radius:4px;margin-top:2px;cursor:default;border:1px solid #334155;display:block}}
.drive-link{{color:#4ade80;font-size:.62rem;text-decoration:none}}
.drive-link:hover{{text-decoration:underline}}
.topic-tag{{font-size:.58rem;background:rgba(56,189,248,.12);color:#38bdf8;padding:1px 4px;border-radius:3px;margin-left:2px}}

/* Threads dropdown panel */
#threads-btn{{background:#1e293b;border:1px solid #334155;color:#38bdf8;font-size:.72rem;border-radius:6px;padding:.35rem .6rem;cursor:pointer}}
#threads-btn:hover{{background:#273449}}
#threads-dropdown{{display:none;position:absolute;top:100%;right:1rem;background:#1a2332;border:1px solid #334155;border-radius:8px;padding:.5rem;max-height:300px;overflow-y:auto;min-width:220px;z-index:50;box-shadow:0 4px 16px rgba(0,0,0,.4)}}
#threads-dropdown.open{{display:block}}
.thread-item{{padding:.4rem .5rem;margin:.1rem 0;border-radius:4px;cursor:pointer;border-left:3px solid transparent;font-size:.68rem;transition:all .15s}}
.thread-item:hover{{border-left-color:#6366f1;background:#0f172a}}
.ti-time{{color:#64748b;font-size:.6rem;margin-right:.3rem}}
.ti-title{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.ti-count{{color:#38bdf8;font-size:.6rem;float:right}}
.empty{{color:#64748b;font-size:.68rem;padding:.5rem;text-align:center}}

/* Thread detail panel */
#tpanel{{display:none;position:fixed;right:0;top:0;width:min(400px,100vw);height:100vh;background:#1e293b;border-left:1px solid #334155;padding:1.5rem;overflow-y:auto;z-index:100;box-shadow:-4px 0 20px rgba(0,0,0,.3)}}
#tpanel.open{{display:block}}
#tclose{{position:absolute;top:.8rem;right:.8rem;background:none;border:none;color:#94a3b8;font-size:1.3rem;cursor:pointer;padding:.3rem .5rem;border-radius:4px}}
#tclose:hover{{color:#fff;background:#334155}}
#tpanel h3{{color:#38bdf8;margin-bottom:.5rem;font-size:.85rem}}
.t-msg{{background:#0f172a;padding:.5rem .7rem;margin:.3rem 0;border-radius:6px;border-left:3px solid #6366f1;font-size:.72rem}}
.t-msg .tm{{color:#64748b;font-size:.58rem}}

/* ── MOBILE ── */
@media(max-width:768px){{
  #topbar{{padding:.4rem .5rem;gap:.3rem}}
  #topbar h2{{font-size:.75rem}}
  .top-stats{{display:none}}
  #stats-toggle{{display:inline-block}}
  .top-stats.expanded{{display:flex;width:100%;gap:.5rem;font-size:.65rem;padding:.2rem 0 .3rem}}
  .top-controls select,.top-controls button,#threads-btn{{font-size:.68rem;padding:.3rem .5rem;flex:1;min-width:80px}}
  #main{{padding:.3rem .4rem}}
  table{{font-size:.68rem;min-width:580px}}
  th,td{{padding:.25rem .35rem}}
  .time-col{{width:55px;font-size:.58rem}}
  .icon-col{{width:20px}}
  .user-col{{min-width:90px;font-size:.62rem}}
  .u-avatar{{width:16px;height:16px}}
  .u-fallback{{width:16px;height:16px;font-size:.55rem}}
  .text-col{{max-width:160px;font-size:.65rem}}
  .group-col{{width:60px;font-size:.62rem}}
  .rating-col{{width:70px;font-size:.62rem}}
  .type-col{{width:40px}}
  #tpanel{{width:100vw}}
}}
@media(max-width:420px){{
  .top-controls{{flex-direction:column;width:100%}}
  .top-controls select,.top-controls button,#threads-btn{{width:100%}}
  table{{font-size:.62rem;min-width:480px}}
  .text-col{{max-width:100px}}
}}
</style></head><body>
<div id="topbar">
  <h2>🧵 LGIAP</h2>
  <div class="top-controls">
    <select id="grp" onchange="filt()">{group_options}</select>
    <select id="rel" onchange="filt()"><option value="">All Messages</option><option value="useful" {rel_sel}>⭐ Useful Only (2+)</option></select>
    <button onclick="filt()">🔄</button>
    <button id="threads-btn" onclick="toggleThreads()" title="Threads">🧵 Threads</button>
  </div>
  <button id="stats-toggle" onclick="toggleStats()">📊</button>
  <div class="top-stats" id="top-stats">
    <span><b>{total}</b> msgs</span>
    <span><b>{groups_cnt}</b> grp</span>
    <span><b>{users_cnt}</b> usr</span>
    <span><b>{useful_cnt}</b> ⭐</span>
  </div>
</div>

<div id="threads-dropdown">
  {thread_html}
</div>

<div id="main">
<table>
<thead><tr><th data-col="0" onclick="toggleCol(0)" title="Click to shrink">🕐<span class="col-hint">↔</span></th><th data-col="1" onclick="toggleCol(1)" title="Click to shrink"><span class="col-hint">↔</span></th><th data-col="2" onclick="toggleCol(2)" title="Click to shrink">👤<span class="col-hint">↔</span></th><th data-col="3" onclick="toggleCol(3)" title="Click to shrink">Type<span class="col-hint">↔</span></th><th data-col="4" onclick="toggleCol(4)" title="Click to shrink">⭐<span class="col-hint">↔</span></th><th data-col="5" onclick="toggleCol(5)" title="Click to shrink">Group<span class="col-hint">↔</span></th><th data-col="6" onclick="toggleCol(6)" title="Click to shrink">Content<span class="col-hint">↔</span></th></tr></thead>
<tbody>{msg_rows}</tbody>
</table>
</div>

<div id="tpanel"><button id="tclose" onclick="closeThread()">✕</button><h3 id="t-title">🧵 Thread</h3><div id="t-content"><p class="empty">Click a message or thread to view...</p></div></div>

<div id="overlay" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:40" onclick="closeThread();closeDropdowns()"></div>

<script>
function filt(){{const g=document.getElementById('grp').value,r=document.getElementById('rel').value;let u='/';const p=[];if(g)p.push('group='+encodeURIComponent(g));if(r)p.push('relevance='+r);if(p.length)u+='?'+p.join('&');location.href=u}}

function toggleThreads(){{const d=document.getElementById('threads-dropdown');d.classList.toggle('open');if(d.classList.contains('open')){{document.getElementById('overlay').style.display='block'}}else{{closeDropdowns()}}}}

function toggleStats(){{const s=document.getElementById('top-stats');s.classList.toggle('expanded')}}

function closeDropdowns(){{document.getElementById('threads-dropdown').classList.remove('open');document.getElementById('overlay').style.display='none'}}

async function openThread(tid){{if(!tid)return;closeDropdowns();document.getElementById('tpanel').classList.add('open');document.getElementById('overlay').style.display='block';document.getElementById('t-content').innerHTML='<p class="empty">Loading...</p>';try{{const r=await fetch('/api/thread/'+tid);const d=await r.json();if(d.error){{document.getElementById('t-content').innerHTML='<p style=color:#ef4444>'+d.error+'</p>';return}}const t=d.thread;document.getElementById('t-title').textContent='🧵 '+(t.topic||t.title||'Thread');let h='<div style=color:#94a3b8;font-size:.7rem;margin-bottom:.5rem>'+t.count+' msgs · '+(t.started||'?').substring(0,16)+'</div>';d.messages.forEach(m=>{{h+='<div class=t-msg><span class=tm>'+(m.time||'').substring(11,16)+'</span> <strong>'+m.name+'</strong><br>'+((m.text||'['+m.type+']')).substring(0,250)+'</div>'}});document.getElementById('t-content').innerHTML=h;document.querySelectorAll('.msg-row').forEach(r=>r.classList.remove('highlight'));document.querySelectorAll('.msg-row[data-thread="'+tid+'"]').forEach(r=>r.classList.add('highlight'))}}catch(e){{document.getElementById('t-content').innerHTML='<p style=color:#ef4444>'+e+'</p>'}}}}

function closeThread(){{document.getElementById('tpanel').classList.remove('open');document.querySelectorAll('.msg-row').forEach(r=>r.classList.remove('highlight'));closeDropdowns()}}

function toggleCol(n){{document.querySelectorAll('[data-col='+n+']').forEach(el=>el.classList.toggle('shrunk'))}}
</script></body></html>'''
