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
            <td class="time-col">{date_str}<br>{time_str}</td>
            <td class="icon-col">{icon}</td>
            <td class="user-col">{user_html}</td>
            <td class="type-col"><span class="type-badge">{mtype}</span></td>
            <td class="rating-col">{badge}{topic_html}</td>
            <td class="group-col" title="{gname}">{gname or gid[:12]}</td>
            <td class="text-col">{display_text}{media_html}</td>
        </tr>'''
    
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LGIAP Archive</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,system-ui,sans-serif;background:#0f172a;color:#e2e8f0;display:flex;height:100vh;overflow:hidden}}
#sidebar{{width:280px;background:#1a2332;border-right:1px solid #334155;padding:1rem;overflow-y:auto;flex-shrink:0}}
#main{{flex:1;padding:1rem;overflow-y:auto}}
h2{{font-size:.9rem;color:#38bdf8;margin-bottom:.5rem}}
select,button{{background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:.4rem .8rem;border-radius:6px;font-size:.75rem;cursor:pointer;width:100%;margin-bottom:.3rem}}
button{{background:#6366f1;border-color:#6366f1;margin-top:.3rem}}
.stats{{display:grid;grid-template-columns:1fr 1fr;gap:.3rem;margin:.5rem 0}}
.scard{{background:#0f172a;padding:.5rem;border-radius:6px;text-align:center;font-size:.7rem}}
.scard .n{{font-size:1rem;font-weight:700;color:#4ade80}}
.sec{{color:#94a3b8;font-size:.65rem;text-transform:uppercase;letter-spacing:1px;margin:1rem 0 .2rem}}
.thread-item{{background:#0f172a;padding:.5rem;margin:.2rem 0;border-radius:6px;cursor:pointer;border-left:3px solid transparent;font-size:.7rem;transition:all .15s}}
.thread-item:hover{{border-left-color:#6366f1;background:#1e293b}}
.ti-time{{color:#64748b;font-size:.6rem;margin-right:.3rem}}
.ti-title{{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.ti-count{{color:#38bdf8;font-size:.6rem;float:right}}
.empty{{color:#64748b;font-size:.7rem;padding:1rem;text-align:center}}
table{{width:100%;border-collapse:collapse;font-size:.78rem}}
th{{background:#1e293b;padding:.4rem .5rem;text-align:left;color:#94a3b8;position:sticky;top:0;z-index:1}}
td{{padding:.3rem .5rem;border-bottom:1px solid #1e293b}}
.msg-row{{cursor:pointer;transition:background .15s}}
.msg-row:hover{{background:rgba(99,102,241,.12)}}
.msg-row.highlight{{background:rgba(56,189,248,.15);border-left:3px solid #38bdf8}}
.time-col{{font-family:monospace;font-size:.65rem;color:#64748b;white-space:nowrap;width:70px}}
.icon-col{{width:25px;text-align:center}}
.user-col{{color:#e2e8f0;font-size:.7rem;min-width:130px;white-space:nowrap}}
.u-avatar{{width:22px;height:22px;border-radius:50%;vertical-align:middle;margin-right:4px;object-fit:cover}}
.u-fallback{{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:#6366f1;color:#fff;font-size:.65rem;font-weight:700;margin-right:4px;vertical-align:middle}}
.u-name{{vertical-align:middle}}
.type-col{{width:55px}}
.rating-col{{width:90px;font-size:.7rem;white-space:nowrap}}
.group-col{{color:#38bdf8;font-size:.7rem;width:90px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.type-badge{{font-size:.6rem;background:#273449;padding:1px 5px;border-radius:3px;color:#64748b}}
.text-col{{max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.msg-thumb{{max-width:80px;max-height:50px;border-radius:4px;margin-top:3px;cursor:default;border:1px solid #334155;display:block}}
.drive-link{{color:#4ade80;font-size:.65rem;text-decoration:none}}
.drive-link:hover{{text-decoration:underline}}
.topic-tag{{font-size:.6rem;background:rgba(56,189,248,.12);color:#38bdf8;padding:1px 5px;border-radius:3px;margin-left:3px}}
#tpanel{{display:none;position:fixed;right:0;top:0;width:400px;height:100vh;background:#1e293b;border-left:1px solid #334155;padding:1.5rem;overflow-y:auto;z-index:100;box-shadow:-4px 0 20px rgba(0,0,0,.3)}}
#tpanel.open{{display:block}}
#tclose{{position:absolute;top:1rem;right:1rem;background:none;border:none;color:#94a3b8;font-size:1.2rem;cursor:pointer}}
#tpanel h3{{color:#38bdf8;margin-bottom:.5rem;font-size:.9rem}}
.t-msg{{background:#0f172a;padding:.5rem .7rem;margin:.3rem 0;border-radius:6px;border-left:3px solid #6366f1;font-size:.75rem}}
.t-msg .tm{{color:#64748b;font-size:.6rem}}
</style></head><body>
<div id="sidebar">
  <h2>🧵 LGIAP Archive</h2>
  <div class="stats">
    <div class="scard"><div class="n">{total}</div>messages</div>
    <div class="scard"><div class="n">{groups_cnt}</div>groups</div>
    <div class="scard"><div class="n">{users_cnt}</div>users</div>
    <div class="scard"><div class="n">{useful_cnt}</div>⭐ useful</div>
    <div class="scard"><div class="n" style="color:#4ade80">✅</div>sync</div>
    <div class="scard"><div class="n" style="color:#f59e0b">🤖</div>AI active</div>
  </div>
  <select id="grp" onchange="filt()">{group_options}</select>
  <select id="rel" onchange="filt()"><option value="">All Messages</option><option value="useful" {rel_sel}>⭐ Useful Only (2+)</option></select>
  <button onclick="filt()">🔄 Apply Filters</button>
  <div class="sec">Recent Threads</div>
  {thread_html}
</div>
<div id="main">
<table>
<thead><tr><th>Time</th><th></th><th>User</th><th>Type</th><th>Rating</th><th>Group</th><th>Content</th></tr></thead>
<tbody>{msg_rows}</tbody>
</table>
</div>
<div id="tpanel"><button id="tclose" onclick="closeThread()">✕</button><h3 id="t-title">🧵 Thread</h3><div id="t-content"><p class="empty">Click a message or thread to view...</p></div></div>
<script>
function filt(){{const g=document.getElementById('grp').value,r=document.getElementById('rel').value;let u='/';const p=[];if(g)p.push('group='+encodeURIComponent(g));if(r)p.push('relevance='+r);if(p.length)u+='?'+p.join('&');location.href=u}}
async function openThread(tid){{if(!tid)return;document.getElementById('tpanel').classList.add('open');document.getElementById('t-content').innerHTML='<p class="empty">Loading...</p>';try{{const r=await fetch('/api/thread/'+tid);const d=await r.json();if(d.error){{document.getElementById('t-content').innerHTML='<p style=color:#ef4444>'+d.error+'</p>';return}}const t=d.thread;document.getElementById('t-title').textContent='🧵 '+(t.topic||t.title||'Thread');let h='<div style=color:#94a3b8;font-size:.7rem;margin-bottom:.5rem>'+t.count+' msgs · '+(t.started||'?').substring(0,16)+'</div>';d.messages.forEach(m=>{{h+='<div class=t-msg><span class=tm>'+(m.time||'').substring(11,16)+'</span> <strong>'+m.name+'</strong><br>'+((m.text||'['+m.type+']')).substring(0,250)+'</div>'}});document.getElementById('t-content').innerHTML=h;document.querySelectorAll('.msg-row').forEach(r=>r.classList.remove('highlight'));document.querySelectorAll('.msg-row[data-thread="'+tid+'"]').forEach(r=>r.classList.add('highlight'))}}catch(e){{document.getElementById('t-content').innerHTML='<p style=color:#ef4444>'+e+'</p>'}}}}
function closeThread(){{document.getElementById('tpanel').classList.remove('open');document.querySelectorAll('.msg-row').forEach(r=>r.classList.remove('highlight'))}}
</script></body></html>'''
