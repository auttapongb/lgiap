#!/usr/bin/env python3
"""Backfill NULL group_names in LGIAP messages table"""
import requests, psycopg2

with open("/data/lgiap/.env") as f:
    for line in f:
        if "LINE_CHANNEL_TOKEN" in line:
            token = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
            break

conn = psycopg2.connect("postgresql://postgres@127.0.0.1:5432/lgiap")
cur = conn.cursor()

cur.execute("SELECT DISTINCT group_id FROM messages WHERE group_name IS NULL AND group_id IS NOT NULL")
null_groups = [r[0] for r in cur.fetchall()]
print(f"Groups needing backfill: {null_groups}")

for gid in null_groups:
    try:
        resp = requests.get(
            f"https://api.line.me/v2/bot/group/{gid}/summary",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5
        )
        if resp.status_code == 200:
            name = resp.json().get("groupName")
            if name:
                cur.execute(
                    "UPDATE messages SET group_name = %s WHERE group_id = %s AND group_name IS NULL",
                    (name, gid)
                )
                conn.commit()
                print(f"  {gid[:12]}... -> {name} ✅")
            else:
                print(f"  {gid[:12]}... -> groupName is null in API")
        else:
            print(f"  {gid[:12]}... -> HTTP {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"  {gid[:12]}... -> ERROR: {e}")

cur.execute("SELECT COUNT(*) FROM messages WHERE group_name IS NULL AND group_id IS NOT NULL")
remaining = cur.fetchone()[0]
print(f"\nRemaining NULL group names: {remaining}")
conn.close()
