# LGIAP — LINE Group Intelligence & Archive Platform

> **Status:** 🟢 LIVE | **VPS:** Contabo 13.140.145.203 | **Last updated:** 2026-06-08

---

## 🔄 Pipeline Architecture

```
LINE Users → Nginx (:443) → lgiap-api FastAPI (:8085) → Redis (:6379) → Dramatiq Workers ×2 → PostgreSQL (:5432) → Dashboard
```

### Message Flow
1. User sends message in LINE group with bot
2. LINE Platform POSTs webhook to `https://lgiap.sasin.cfoth.ai/webhook`
3. Nginx (Let's Encrypt SSL) proxies to localhost:8085
4. lgiap-api verifies `X-Line-Signature` using `LINE_CHANNEL_SECRET`
5. LINE SDK parses event → `queue_message.send()` enqueues to Redis
6. Dramatiq workers dequeue → insert to PostgreSQL `messages` table
7. Dashboard fetches from DB via API, renders in browser

---

## 🖥️ Services (all PM2-managed on 13.140.145.203)

| Service | Port | Memory | 
|---------|------|--------|
| lgiap-api | 8085 | ~92MB |
| lgiap-worker (×2) | — | ~25MB |
| hub-server | 8081 | ~48MB |
| brain-server | 8400 | ~32MB |
| dashboard | 8888 | ~40MB |
| capture-server | 8896 | ~83MB |
| naruto-web-ui | 4790 | ~42MB |
| upload-server | 8897 | ~23MB |
| gemini-vision | 8499 | ~45MB |
| PostgreSQL | 5432 | — |
| Redis | 6379 | — |
| nginx | 80/443 | — |

---

## 🔧 Quick Fixes

### No messages in dashboard
```bash
pm2 status | grep lgiap-worker  # workers running?
sudo -u postgres psql -d lgiap -c "SELECT count(*) FROM messages;"
grep LineBotWebhook /var/log/nginx/access.log | tail -5  # 200 = good
```

### Webhook 400 (Invalid signature)
→ Reissue Channel Secret in LINE Console, update `/data/lgiap/.env`, restart lgiap-api.

### Workers not processing
```bash
pm2 restart lgiap-worker
# Or manual:
cd /data/lgiap/backend && nohup venv/bin/python3 -m dramatiq app.tasks.ingest --processes 2 &
```

### Full restart after reboot
```bash
pm2 resurrect
pm2 save
```

---

## 🔑 Configuration

- **LINE Console:** https://developers.line.biz/console/channel/1653536919
- **Webhook URL:** `https://lgiap.sasin.cfoth.ai/webhook`
- **.env:** `/data/lgiap/.env`
- **SSL:** Let's Encrypt, auto-renew via certbot
- **DB:** PostgreSQL 17, peer auth for localhost

---

*See GODJI_RECOVERY.md for full rebuild instructions.*
