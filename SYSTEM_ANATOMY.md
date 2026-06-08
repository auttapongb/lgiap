# CFOTH Infrastructure — System Anatomy & Recovery Guide

> **SSOT**: This document. All bots (Godji, Mew, Ginnie) reference this first.

## 📍 Architecture

```
┌── OLD Contabo (185.218.125.121) ──┐   ┌── NEW Contabo (13.140.145.203) ──┐
│  6 CPU / 11GB / 193GB              │   │  12 CPU / 47GB / 484GB             │
│                                    │   │                                    │
│  Godji-Hermes (commander)          │   │  Ginnie (worker + Discord)         │
│  Docker: hermes-bot                │   │  systemd: hermes-ginnie            │
│  Port: 8642 (internal)             │   │  Port: 8645                        │
│                                    │   │  Config: /root/.hermes-ginnie/     │
│  Mew Hermes (worker)               │   │                                    │
│  systemd: hermes-mew               │   │  ALL SERVICES: see below           │
│  Port: 8644                        │   │                                    │
│  Config: /root/.hermes-mew/        │   │  nginx → ALL domains               │
│                                    │   │  PostgreSQL → lgiap, paperclip...  │
└────────────────────────────────────┘   │  Redis → LGIAP + langfuse          │
                                         │  Ollama → embeddings               │
                                         └────────────────────────────────────┘
```

## 🔑 SSH Access

| VPS | IP | Key | Command |
|-----|-----|-----|---------|
| Old Contabo | 185.218.125.121 | /root/.ssh/hermes_key | `ssh -i ~/.ssh/hermes_key root@185.218.125.121` |
| New Contabo | 13.140.145.203 | /root/.ssh/hermes_key | `ssh -i ~/.ssh/hermes_key root@13.140.145.203` |

## 🤖 Agents

| Agent | Host | Runtime | Config | Port | Restart Command |
|-------|------|---------|--------|------|-----------------|
| **Godji** | Old Contabo | Docker `hermes-bot` | `/root/.hermes/config.yaml` | 8642 | `docker restart hermes-bot` |
| **Mew** | Old Contabo | systemd `hermes-mew` | `/root/.hermes-mew/config.yaml` | 8644 | `systemctl restart hermes-mew` |
| **Ginnie** | New Contabo | systemd `hermes-ginnie` | `/root/.hermes-ginnie/config.yaml` | 8645 | `systemctl restart hermes-ginnie` |

## 📦 Services (New Contabo — 13.140.145.203)

### OS-Level (PM2 or raw)

| Service | Port | Manager | Status Check |
|---------|------|---------|-------------|
| hub-server | 8081 | raw python3 | `curl localhost:8081` |
| capture-server | 8895 | raw python3 | `curl localhost:8895` |
| brain-server | 8400 | raw python3 | `curl localhost:8400/api/search?q=test` |
| lgiap-api | 8085 | raw python3 | `curl localhost:8085/health` |
| upload-server | 8897 | raw python3 | `curl localhost:8897` |
| whisper-server | 8896 | PM2 | `pm2 status whisper-server` |
| live-bot | 9000 | PM2 | `pm2 status live-bot` |
| openmaic | — | PM2 | `pm2 status openmaic` |
| gemini-vision | 8499 | raw python3 | `curl localhost:8499` |

### Docker

| Service | Port | Status Check |
|---------|------|-------------|
| n8n | 5678 | `curl localhost:5678/healthz` |
| langfuse | 3031 | `docker ps \| grep langfuse` |
| deeptutor | 3782,8001 | `curl localhost:8001/health` |
| searxng | — | `docker ps \| grep searxng` |
| deep-research | 5000 | `curl localhost:5000` |

### Infrastructure

| Service | Port | Check |
|---------|------|-------|
| PostgreSQL | 5432 | `psql -U postgres -h 127.0.0.1 -c "SELECT 1"` |
| Redis | 6379 | `redis-cli PING` |
| nginx | 80,443 | `systemctl status nginx` |
| Ollama | 11434 | `curl localhost:11434/api/tags` |

## 🌐 Domains (all → 13.140.145.203)

| Domain | Backend |
|--------|---------|
| sasin.cfoth.ai | :8081 |
| capture.sasin.cfoth.ai | :8895 |
| brain.cfoth.ai | :8400 |
| lgiap.sasin.cfoth.ai | :8085 |
| dashboard.cfoth.ai | :8085/control |
| classroom.sasin.cfoth.ai | openmaic |
| learn.sasin.cfoth.ai | deeptutor |
| live.sasin.cfoth.ai | :9000 |
| langfuse.cfoth.ai | langfuse Docker |
| n8n.brain.cfoth.ai | n8n Docker |
| paperclip.cfoth.ai | :3100 |
| autta.cfoth.ai | api |
| fb.cfoth.ai | static |
| interview.cfoth.ai | static |
| landing.cfoth.ai | static |
| ruza.cfoth.ai | static |

## 🔄 Recovery Chain

```
Godji monitors → Mew (old Contabo) + Ginnie + services (new Contabo)
Mew monitors → Godji (old Contabo)
Ginnie monitors → services (new Contabo)
```

| Failure | Detector | Recovery Command |
|---------|----------|-----------------|
| Godji down | Mew | `docker restart hermes-bot` |
| Mew down | Godji | `systemctl restart hermes-mew` |
| Ginnie down | Godji | `ssh root@13.140.145.203 systemctl restart hermes-ginnie` |
| Service down | Ginnie | `systemctl restart SERVICE` or `pm2 restart NAME` |
| PostgreSQL down | Ginnie | `systemctl restart postgresql` |
| nginx down | Ginnie | `systemctl restart nginx` |

## 🛡 Godji Immortality

- Docker: `--restart=always`
- Systemd override: `Restart=always` + `RestartSec=5`
- Mew health check: every 30s → `curl localhost:8642/health`
- Minimal dependencies: only needs Docker + network

## ⏰ Cron Jobs (New Contabo)

| Job | Schedule | Action |
|-----|----------|--------|
| godji-health-check | */5 * * * * | Check all agents |
| service-monitor | */1 * * * * | PM2 + Docker health |
| vault-sync | */30 * * * * | Obsidian git sync |
| certbot-renew | 0 3 * * * | SSL cert renewal |

## 🗄 Databases (New Contabo — PostgreSQL :5432)

| Database | Purpose | Backup |
|----------|---------|--------|
| lgiap | LINE messages, groups, users | Daily pg_dump |
| paperclip | Paperclip platform | Daily pg_dump |
| langfuse | LLM observability | Daily pg_dump |

## 📊 Dashboard

URL: https://dashboard.cfoth.ai (→ 13.140.145.203 :8085/control)

All bots load this first to understand the system state before any action.

---

*Last updated: migration day 0. Update this when adding/removing services.*
