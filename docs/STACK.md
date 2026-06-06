# LGIAP — Technology Stack Decisions

**Date:** 2026-06-06 | **Researched by:** Hermes Agent

---

## 1. LINE Integration

### Decision: `line-bot-sdk` v3.23.0 (Official LINE SDK)

**PyPI:** `line-bot-sdk` | **GitHub:** `line/line-bot-sdk-python` | **Python:** >= 3.10

**Why not alternatives?**
- This is the **only** Python SDK maintained by LINE Corporation
- Includes FastAPI example (`examples/fastapi-echo`) — fits our stack
- Built-in webhook signature verification via `WebhookHandler`
- Parses all event types: MessageEvent, JoinEvent, LeaveEvent, UnsendEvent, MemberJoinEvent, MemberLeaveEvent
- Media download via LINE Content API (`MessagingApi.get_message_content()`)
- Actively maintained (v3.23.0 as of June 2026, 70+ releases)

**Limitations to plan for:**
- Group bot requires LINE Official Account (Messaging API plan)
- Media download URLs are time-limited — must download immediately
- No access to historical messages before bot joins
- User profile access limited (display name only from message metadata)
- Sticker metadata available (packageId, stickerId) but no sticker image API

**Webhook best practices:**
1. Verify `X-Line-Signature` header before processing (LINE SDK handles this)
2. `response 200` within 1 second or LINE retries
3. Queue heavy processing after ACK — never block the webhook
4. Store raw `destination` property to identify which bot/group received the event
5. Handle duplicate events via message ID deduplication

---

## 2. Message Queue

### Decision: Dramatiq + Redis (MVP) → Google Pub/Sub or Kafka (scale)

**Why Dramatiq?**
| | Dramatiq | Celery | Redis RQ |
|---|---|---|---|
| Throughput | **1,200 tasks/sec** | 950/sec | ~800/sec |
| Memory (2 vCPUs) | **180 MB** | 260 MB | ~200 MB |
| API complexity | Simple decorators | Complex config | Simple |
| Retry handling | Built-in backoff | Manual config | Basic |
| Monitoring | Prometheus | Flower | rq-dashboard |
| Redis required | Yes | Yes | Yes |

**Dramatiq advantage:** Designed as "Celery done right" — no global state, predictable retry behavior, middleware-based.

**Queue topology:**
```
webhook → immediate ACK → raw_store_queue (high priority)
                         → media_download_queue
                         → embedding_queue (normal)
                         → ai_summary_queue (low, batch)
```

**Key config:**
```python
import dramatiq
from dramatiq.brokers.redis import RedisBroker

redis_broker = RedisBroker(url="redis://localhost:6379/0")
dramatiq.set_broker(redis_broker)

@dramatiq.actor(max_retries=3, min_backoff=5000, max_backoff=60000)
def download_media(message_id: str):
    ...
```

---

## 3. Database

### Decision: PostgreSQL + pgvector + TimescaleDB (hypertable for messages)

**Why not separate vector DB?**
- Already running PostgreSQL on VPS → zero new infrastructure
- `pgvector` 0.8.2 handles ~1.8M messages/year comfortably (5-year horizon: ~9M)
- Full SQL JOINs between messages, embeddings, users, metadata
- ACID: message + embedding in one transaction

**Schema overview:**
```
messages (TimescaleDB hypertable, partitioned by day)
  ├── id, group_id, user_id, timestamp, message_type
  ├── text_content, raw_event_json
  └── embedding VECTOR(1024) via pgvector

groups, users, group_members
media_assets, links
topics, action_items, decisions
summaries, embeddings
audit_logs
```

**When to migrate:** Only if hybrid BM25+vector search becomes critical or volume exceeds 5M+ vectors. Then: Weaviate (native BM25, better at scale).

---

## 4. AI / LLM Pipeline

### Primary Model: Gemini 3.1 Flash

| Task | Model | Why |
|---|---|---|
| Summarization (daily) | Gemini 3.1 Flash | 1M context fits full day; $0.50/$3.00 per 1M tok |
| Topic labeling | GPT-5.4 mini or local WangchanLION | Batch; cost-sensitive |
| Action item extraction | Claude Sonnet 4.6 | Best structured extraction |
| Decision extraction | Claude Sonnet 4.6 | Nuanced understanding |
| RAG Q&A | Gemini 3.1 Flash + reranker | Vector retrieval → rerank → answer |
| Thai-heavy batch | WangchanLION-v3 (local, Ollama) | Zero API cost; 47B Thai tokens trained |

### Embeddings: bge-m3 (BAAI)

- 1024 dimensions, 100+ languages including Thai
- Top SEA-BED benchmark performer for SEA languages
- Self-hosted → free, no API costs
- Deploy via Ollama or vLLM

### RAG Pipeline
```
User query → bge-m3 embedding → pgvector cosine search (top-20)
  → PG full-text search (tsvector keyword)
  → Reranker (Cohere Rerank 3 or bge-reranker-v2) → top-5
  → Gemini 3.1 Flash answer (cite sources)
```

### Topic Clustering: BERTopic + LLM labels
```
Messages → bge-m3 embeddings → HDBSCAN clustering
  → Representative docs per cluster
  → Gemini Flash: "Name this topic cluster based on these messages"
  → Store topic_id back to messages
```

---

## 5. Knowledge Graph

### Decision: LightRAG (PostgreSQL) for MVP, Neo4j for scale

**LightRAG approach:**
- Entity extraction: People, Topics, Files, Decisions, Action Items
- Relationship extraction: MENTIONS, SHARED, ASSIGNED_TO, DECIDED_BY
- Dual retrieval: vector (pgvector) + graph (recursive CTEs)
- All in PostgreSQL — no new infrastructure

**When Neo4j:**
- Multi-hop queries become common (e.g., "who decided what about which topic")
- Dedicated graph visualization in dashboard
- Community/engagement analytics

---

## 6. Frontend

### Decision: Next.js 15 + TypeScript + TailwindCSS + ShadCN UI ✅

**Validated against alternatives:**

| Alternative | Verdict |
|---|---|
| Streamlit | ❌ Full page reruns kill timeline replay and AI streaming |
| FastAPI + Jinja2 | ❌ 2008 template engine, no modern UX |
| FastAPI + HTMX | ⚠️ Viable but much more custom code |
| Reflex | ❌ Immature, no AI SDK, no streaming |

**Key libraries:**
| Feature | Library |
|---|---|
| AI Chat | Vercel AI SDK (`useChat`, streaming, multi-provider) |
| Timeline Replay | `shadcn-timeline` + DayPilot |
| Semantic Search | Drizzle ORM + pgvector |
| File Library | ShadCN File Manager template |
| Admin | 13+ shadcn/ui dashboard variants |
| PDF Export | Puppeteer / @react-pdf/renderer |
| Auth | NextAuth.js v5 + Google OAuth |

**Hybrid architecture:** Next.js for frontend + FastAPI for backend API (Python AI logic).

---

## 7. Media Processing

| Type | Tool | Notes |
|---|---|---|
| Images | Vision LLM (Gemini) for OCR | Extract text from whiteboard/slide photos |
| PDFs | PyPDF2 / Marker | Text extraction, indexing |
| DOCX/PPTX/XLSX | python-docx / python-pptx / openpyxl | Metadata + content extraction |
| Audio | faster-whisper (small model) | Speech-to-text, 500MB model |
| Video | ffmpeg thumbnails + Whisper transcript | Extract key frames + audio track |
| Stickers | Metadata only (packageId + stickerId) | LINE API limitations |

---

## 8. Cost Optimization Strategies

1. **Store raw media in GCS/S3 cold storage** (lifecycle: 30 days hot → cold)
2. **Batch AI processing** — daily summaries, not real-time
3. **Cache repeated AI answers** — Redis, 24h TTL
4. **Use local models for high-volume tasks** — WangchanLION for Thai, bge-m3 for embeddings
5. **Embedding batching** — process 50 messages at once, not one by one
6. **Only embed meaningful text** — skip stickers, short reactions, URLs
7. **Lifecycle policies** — compress thumbnails, delete previews after 90 days

---

## 9. Decision Matrix

| Decision | Pick | Alternative |
|---|---|---|
| LINE SDK | `line-bot-sdk` (official) | N/A (only one) |
| Queue | Dramatiq + Redis | Celery (too complex), RQ (too basic) |
| Vector DB | pgvector | Weaviate/Pinecone (add when scaling) |
| KG | LightRAG on PG | Neo4j (add for graph traversal) |
| Primary LLM | Gemini 3.1 Flash | GPT-5.4 mini (worse Thai, more $) |
| Embeddings | bge-m3 (free) | Cohere Embed v4 (paid) |
| Thai LLM | WangchanLION-v3 (local) | Typhoon-2 |
| Frontend | Next.js + ShadCN | Streamlit (fundamentally wrong) |
| Auth | NextAuth.js + Google | Clerk (paid, more features) |
