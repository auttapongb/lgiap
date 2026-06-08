#!/usr/bin/env python3
"""Backfill AI ratings for pending messages — robust JSON parsing"""
import sys, os, re
sys.path.insert(0, "/data/lgiap/backend")
env_file = "/data/lgiap/.env"
with open(env_file) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ[key] = val.strip().strip("'").strip('"')

from app.config import DATABASE_URL
import psycopg2, json, requests

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

cur.execute("""
    SELECT id, user_id, text_content 
    FROM messages 
    WHERE ai_rating = -1 AND message_type = 'text' AND text_content != ''
""")
pending = cur.fetchall()
print(f"Backfilling {len(pending)} messages...")

for msg_id, user_id, text in pending:
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={os.environ['GEMINI_API_KEY']}",
            json={
                "contents": [{"parts": [{"text": f'Rate this LINE message 0-3 (0=social,1=logistics,2=useful,3=critical). Return ONLY JSON like {{"rating":0,"reason":"short","topic":"short"}}. Message: "{text[:300]}"'}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200}
            },
            timeout=20
        )
        data = resp.json()
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        
        # Parse robustly
        raw = raw.strip()
        # Remove markdown fences
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        
        # Try direct parse
        try:
            result = json.loads(raw)
        except:
            # Extract just rating with regex
            m = re.search(r'"rating"\s*:\s*(\d)', raw)
            rating = int(m.group(1)) if m else 0
            t = re.search(r'"topic"\s*:\s*"([^"]*)"', raw)
            topic = t.group(1) if t else ""
            result = {"rating": rating, "suggested_topic": topic}
        
        rating = result.get("rating", 0)
        topic = result.get("suggested_topic", result.get("topic", ""))
        
        cur.execute("UPDATE messages SET ai_rating = %s, ai_topic = %s WHERE id = %s",
                    (rating, topic, msg_id))
        conn.commit()
        print(f"  msg {msg_id}: ⭐{rating} {topic}")
    except Exception as e:
        print(f"  msg {msg_id}: ❌ {str(e)[:80]}")

cur.execute("SELECT COUNT(*) FROM messages WHERE ai_rating = -1")
remaining = cur.fetchone()[0]
print(f"\nRemaining pending: {remaining}")
conn.close()
