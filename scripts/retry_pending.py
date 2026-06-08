#!/usr/bin/env python3
"""Retry msg 14 and show rating distribution"""
import sys, os, re
sys.path.insert(0, "/data/lgiap/backend")
env_file = "/data/lgiap/.env"
with open(env_file) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ[key] = val.strip().strip("'").strip('"')

import psycopg2, requests
from app.config import DATABASE_URL

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# Retry msg 14
cur.execute("SELECT id, user_id, text_content FROM messages WHERE id = 14")
mid, uid, text = cur.fetchone()

for attempt in range(3):
    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={os.environ['GEMINI_API_KEY']}",
            json={
                "contents": [{"parts": [{"text": f'Rate this LINE message 0-3: 0=social,1=logistics,2=useful,3=critical. Return JSON: {{"rating":0,"topic":"short"}}. Message: "{text[:250]}"'}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200}
            },
            timeout=30
        )
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        m = re.search(r'"rating"\s*:\s*(\d)', raw)
        rating = int(m.group(1)) if m else 0
        t = re.search(r'"topic"\s*:\s*"([^"]*)"', raw)
        topic = t.group(1) if t else ""
        cur.execute("UPDATE messages SET ai_rating=%s, ai_topic=%s WHERE id=%s", (rating, topic, mid))
        conn.commit()
        print(f"msg {mid}: star={rating}, topic={topic}")
        break
    except Exception as e:
        print(f"Attempt {attempt+1}: {str(e)[:100]}")

cur.execute("SELECT ai_rating, COUNT(*) FROM messages GROUP BY ai_rating ORDER BY ai_rating")
print("\nRating distribution:")
labels = {-1: "pending", 0: "social", 1: "logistics", 2: "useful", 3: "critical"}
for r, c in cur.fetchall():
    print(f"  {labels.get(r, r)}: {c} msgs")
conn.close()
