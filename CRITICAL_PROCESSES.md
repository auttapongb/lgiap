# LGIAP — Critical Processes (DO NOT KILL)

This document lists every recurring/background process that must stay running
for the LGIAP LINE message pipeline to function. If any of these die, messages
stop being ingested, stored, rated, or displayed.

---

## 🔴 Tier 1 — Message Pipeline (kill = LINE messages lost)

| Process | PM2 Name | Port | What It Does | Restart |
|---------|----------|------|-------------|---------|
| **lgiap-api** | `lgiap-api` | 8085 | FastAPI: receives LINE webhooks, serves dashboard | `pm2 restart lgiap-api` |
| **lgiap-worker** | `lgiap-worker` | — | Dramatiq: ingests messages into PostgreSQL, calls Gemini for AI rating, auto-syncs LINE user profiles | `pm2 restart lgiap-worker` |

## 🟡 Tier 2 — Periodic Analysis (kill = no threads/ratings for new msgs)

| Process | Schedule | What It Does | Restart |
|---------|----------|-------------|---------|
| **Analyzer cron** | `*/5 * * * *` | Runs `analyzer.py`: rates unrated messages, assigns conversation threads, syncs profiles, downloads media | `crontab -e` (see crontab) |

## 🟢 Tier 3 — Supporting Services (kill = degraded features)

| Process | PM2 Name | Port | What It Does | Restart |
|---------|----------|------|-------------|---------|
| **nginx** | systemd | 80/443 | Reverse proxy: routes `lgiap.sasin.cfoth.ai` → :8085, handles SSL | `systemctl restart nginx` |
| **PostgreSQL** | systemd | 5432 | Database: stores all messages, profiles, ratings, threads | `systemctl restart postgresql` |
| **Redis** | systemd | 6379 | Queue broker: Dramatiq message queue (password: langfuse2026) | `systemctl restart redis-server` |

---

## 📋 PM2 Process Map

```
pm2 list   →   see all running processes
pm2 save   →   save current state (auto-start on reboot)
pm2 resurrect → restore saved processes
```

Crontab: `crontab -l`

---

## 🔄 Auto-Recovery

PM2 auto-restarts crashed processes. PostgreSQL and Redis auto-start via systemd.
The analyzer cron runs independently — if cron dies, threads/ratings won't update
but messages still get ingested raw.
