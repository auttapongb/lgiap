# LGIAP — LINE Group Intelligence & Archive Platform

> **Permanent institutional memory powered by AI.**  
> Capture, archive, organize, analyze, and retrieve LINE group communications.

---

## Tech Stack (Researched & Validated — 2026-06-06)

| Layer | Choice | Why |
|---|---|---|
| **Messaging** | `line-bot-sdk` v3.23 (official LINE SDK) | FastAPI example built-in, all event types, signature verification |
| **Backend** | FastAPI + Python 3.12 | Async, production-grade, built-in webhook support |
| **Queue** | **Dramatiq** + Redis | 25% faster than Celery, 30% less RAM, simpler API |
| **Database** | PostgreSQL + TimescaleDB partition | Relational + vector in one DB |
| **Vector DB** | **pgvector** 0.8.2+ | Zero new infrastructure (already have PG) |
| **Embeddings** | **bge-m3** (1024-dim, self-hosted) | Top SEA-BED multilingual performer, free |
| **Primary LLM** | **Gemini 3.1 Flash** | Best Thai price-performance, 1M context, $0.50/1M input |
| **Extraction LLM** | Claude Sonnet 4.6 | Best for decisions/action items |
| **Knowledge Graph** | LightRAG (on PG) → Neo4j (at scale) | Graph+vector from same DB |
| **Topic Clustering** | BERTopic + bge-m3 | Modular, reproducible, Thai-capable |
| **Frontend** | Next.js 15 + TypeScript + TailwindCSS + ShadCN UI | AI SDK streaming, 33K+ star ecosystem |
| **Auth** | NextAuth.js v5 + Google OAuth | EMBA cohort identity |
| **Storage** | Google Cloud Storage / S3 | Media archive, signed URLs |
| **Hosting** | Contabo VPS (existing) | Self-hosted, no vendor lock-in |

## Cost Estimate (MVP)

| Component | Monthly |
|---|---|
| LLM API (Gemini Flash) | ~$50–80 |
| LLM API (Claude extraction) | ~$50–80 |
| PostgreSQL (existing VPS) | $0 |
| bge-m3 embeddings (local) | $0 |
| Redis (existing VPS) | $0 |
| Object Storage (10-50 GB) | ~$5 |
| **Total** | **~$105–165/mo** |

## Quick Start

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Workers
dramatiq app.tasks

# Frontend
cd frontend
pnpm install
pnpm dev
```

## Project Structure

```
lgiap/
├── backend/           # FastAPI + Dramatiq workers
│   ├── app/
│   │   ├── main.py           # FastAPI app + health
│   │   ├── config.py          # Settings
│   │   ├── webhooks/          # LINE webhook handler
│   │   ├── models/            # SQLAlchemy models
│   │   ├── tasks/             # Dramatiq tasks (media dl, AI)
│   │   ├── ai/                # LLM pipeline, RAG, embeddings
│   │   ├── storage/           # Object storage adapters
│   │   └── api/               # Dashboard REST API
│   ├── alembic/               # DB migrations
│   └── requirements.txt
├── frontend/          # Next.js + ShadCN UI dashboard
│   └── src/
│       ├── app/               # App Router pages
│       ├── components/        # shadcn/ui components
│       └── lib/               # API client, utils
├── docs/
│   ├── ARCHITECTURE.md        # System architecture
│   ├── STACK.md               # Technology decisions
│   └── AI-PIPELINE.md         # LLM pipeline design
├── docker-compose.yml
└── README.md
```

## Architecture

```
LINE Group → LINE Messaging API → Webhook (FastAPI)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              Raw Event Store   Dramatiq Queue   Signature ✓
              (PostgreSQL)      (Redis)          ACK to LINE
                    │               │
                    │    ┌──────────┼──────────┐
                    │    ▼          ▼          ▼
                    │  Media DL   Embedding   AI Pipeline
                    │  (GCS)      (bge-m3)    (Gemini)
                    │    │          │          │
                    └────┼──────────┼──────────┘
                         ▼          ▼
                    PostgreSQL   pgvector
                         │          │
                         └────┬─────┘
                              ▼
                    Next.js Dashboard
                    (Search, Replay, AI Chat)
```

## Phase Roadmap

| Phase | Duration | Deliverables |
|---|---|---|
| **1: Foundation** | 2 weeks | LINE webhook, message storage, basic replay, search |
| **2: Intelligence** | 2 weeks | Daily summaries, topic clustering, embeddings, semantic search |
| **3: Advanced AI** | 2 weeks | Thread reconstruction, knowledge graph, Q&A, action items |
| **4: Dashboard** | 2 weeks | Full Next.js dashboard, AI chat, admin, export |
| **5: Polish** | 2 weeks | Auth, rate limiting, monitoring, deployment |

## License

MIT
