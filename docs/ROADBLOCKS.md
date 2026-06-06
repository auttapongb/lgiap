# LGIAP — Comprehensive Roadblocks & Integration Plan

**Date:** 2026-06-06 | **Status:** Pre-build audit

---

## ⚠️ CRITICAL ROADBLOCKS (Must Solve Before Any Code)

### R1: LINE Official Account — Group Bot Limitations

**Problem:** LINE restricts group bots. Not all LINE Official Account plans support group messaging.

**Status:** 🔴 MUST VALIDATE BEFORE STARTING

| Plan Type | Group Messages? | Cost |
|---|---|---|
| Developer Trial (free) | ❌ No groups | $0 |
| Messaging API (paid) | ✅ Yes | Varies |
| LINE Business Connect | ✅ Yes | Enterprise |

**Action:** Create a LINE Developer account, check which plan allows group webhooks. If the free developer trial doesn't support groups, we need a paid plan BEFORE writing any code.

**Fallback:** Use Telegram instead (groups work on free tier). The multi-platform architecture supports this swap.

---

### R2: LINE Media Content API — Time-Limited URLs

**Problem:** LINE media download URLs expire quickly (minutes, not hours).

**Must-do:**
1. Download media IN the webhook handler or within 1-2 minutes via queue
2. Store immediately in object storage (GCS/S3/local)
3. Never store the LINE URL — store your own URL

**Design decision:** Media download MUST be synchronous/immediate in the webhook flow, NOT batched overnight. This might require a high-priority queue.

---

### R3: Webhook Reliability — LINE Retry Behavior

**Problem:** LINE retries webhooks that don't respond within 1 second. Duplicate events are common.

**Must-do:**
1. ACK within 500ms max (store raw event, respond 200)
2. Deduplicate by message ID before DB insert
3. Idempotent processing — same event processed twice = same result

**Pattern:**
```python
@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature")
    
    # Step 1: Verify signature (blocking, fast)
    handler.handle(body, signature)  # raises InvalidSignatureError
    
    # Step 2: ACK immediately
    # Step 3: Queue processing (don't await)
    background_tasks.add_task(queue_message, body)
    
    return Response("OK", status_code=200)
```

---

### R4: PostgreSQL Partitioning at Scale

**Problem:** 100K+ messages/month × multiple groups × years = millions of rows. Full table scans become slow.

**Must-do:** TimescaleDB hypertable on messages by day:
```sql
SELECT create_hypertable('messages', 'timestamp', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON messages (group_id, timestamp DESC);
CREATE INDEX ON messages USING ivfflat (embedding vector_cosine_ops);  -- pgvector
```

**Without this:** After ~500K messages, searches slow to 5+ seconds (unacceptable).

---

### R5: LINE User ID vs Display Name — No Profile API for Groups

**Problem:** LINE does NOT expose user profile information (real name, profile picture) via Messaging API for group messages. You only get:
- `userId`: opaque string (changes if user blocks/re-adds bot)
- `displayName`: set by user in that group context, inconsistent

**Must-do:**
1. Do NOT rely on userId being permanent
2. Store ALL display names used by a user (historical tracking)
3. Build a user identity resolution layer (manual or inferred): "user_abc123" → "Bank" (from context)
4. Accept that some attribution will be approximate

---

### R6: Thai Language Tokenization for Full-Text Search

**Problem:** PostgreSQL `tsvector` tokenizer doesn't split Thai words correctly (no spaces between words).

**Must-do:**
1. Use `pg_bigm` or `pg_thai_parser` extension for Thai tokenization
2. OR: pre-tokenize Thai text before storing (PyThaiNLP `word_tokenize`)
3. OR: rely primarily on pgvector semantic search (bge-m3 handles Thai natively)

**Recommendation:** Use pgvector as primary search + PyThaiNLP tokenization for keyword fallback. bge-m3 embeddings handle Thai semantic search without needing word boundaries.

---

### R7: LINE Bot Cannot Read History Before Join

**Problem:** The bot only sees messages AFTER it's invited. All history before joining is invisible.

**Must-do:**
1. Accept this limitation — clearly communicate to users
2. Option: manually export old chat history (LINE backup) and import as one-time seed data
3. Option: use `chat-history-manager` (supports LINE export) for initial seed

**Timeline note:** The sooner the bot is invited to groups, the sooner history begins accumulating.

---

### R8: Cost Creep — AI Processing at Scale

**Problem:** At 10 groups × 500 msgs/day = 150K messages/month. Every message goes through:
- Embedding (bge-m3, local, free)
- Storage (PostgreSQL, existing, free)

But daily AI processing (summaries, extraction) costs scale with message volume:
- 150K messages/month → ~$100-160/month in LLM costs
- If groups grow to 50 → $500-800/month

**Must-do:**
1. Batch processing: 1 AI summary per day per group (not per message)
2. Only process "meaningful" messages (skip stickers, reactions, short replies)
3. Use WangchanLION-v3 (local, free) for high-volume Thai tasks
4. Cache AI results aggressively (Redis, 24h TTL)
5. Implement cost monitoring + hard cap by group

---

### R9: Dependency Conflicts

**Problem:** The stack mixes two ecosystems:

| Component | Python | Node |
|---|---|---|
| LINE bot + FastAPI | ✅ | |
| Dramatiq workers | ✅ | |
| Embeddings (bge-m3) | ✅ | |
| AI pipeline (LangChain) | ✅ | |
| Next.js dashboard | | ✅ |
| ShadCN UI | | ✅ |

**Potential issues:**
1. Python 3.12+ — `line-bot-sdk` requires >= 3.10. `bge-m3` works with 3.12. Fine.
2. Node 20+ for Next.js 15 — check VPS node version
3. PostgreSQL 15+ for pgvector 0.8.x — check VPS PG version
4. Redis 7+ for Dramatiq — must install on VPS

**Action:** Verify all versions on target VPS before starting.

---

### R10: NGINX Port Conflicts — Existing Services on VPS

**Problem:** The Contabo VPS already runs:
- nginx on 80/443 (Sasin Hub, capture, brain, tools)
- PM2-managed services (DeepTutor, OpenMAIC, whisper)

**Must-do:**
1. LGIAP webhook must be on a NEW port (suggest 8085) — NOT 80/443
2. Add nginx reverse proxy for `lgiap.sasin.cfoth.ai` → port 8085
3. Dashboard on port 3000 (Next.js default) or behind nginx
4. Create new Cloudflare DNS record + SSL cert
5. Do NOT interfere with existing services

---

### R11: embedb-second-brain Integration — JSON Schema Mismatch

**Problem:** The 2nd Brain's `corpus.json` has a specific schema each entry must match:
```json
{
  "name": "filename",
  "title": "AI-generated title",
  "summary": "2-3 sentence summary",
  "frameworks": ["Porter's Five Forces"],
  "topics": ["Strategy"],
  "key_concepts": ["concept1", "concept2"],
  "difficulty": "foundational",
  "reading_time_min": 5,
  "tags": ["tag1"],
  "drive_id": "...",  // LINE messages don't have this!
  "source_folder": "EMBA2026",
  "content": "raw text",
  "size": 1234,
  "synced_at": "ISO timestamp"
}
```

**Problem:** LINE messages don't have `drive_id` — this field is used as the primary key for upsert in `update_corpus()`. Without it, the safety filter `[e for e in corpus if e.get("drive_id")]` strips all LINE entries.

**Solution:** Use `line_message_id` as the `drive_id` surrogate:
```python
entry = {
    "drive_id": f"line_{message_id}",  # surrogate key
    "source_folder": f"LINE/{group_name}",
    "name": f"msg_{message_id}.txt",
    ...
}
```

The `size` field must be > 50 chars or `build_graph.py` drops the entry. Use `len(summary_text)` as fallback for short messages.

---

### R12: AI Filtering — What Is "Useful"?

**Problem:** 500 messages/day in an EMBA group. Maybe 20 are actually useful knowledge. How does the AI decide what to keep?

**Proposed heuristic pipeline:**
1. **Pre-filter (code):** Skip stickers, reactions, URLs without context, "ครับ", "ค่ะ", "OK", single emoji
2. **Classifier (Gemini Flash, cheap):** Rate each message 0-3:
   - 0 = social/banter (skip)
   - 1 = coordination ("where is class?") (skip)
   - 2 = useful knowledge (keep)
   - 3 = critical (assignment, deadline, professor instruction) (keep + flag)
3. **Only messages rated 2-3** get embedded, stored in 2nd Brain

**Prompt template:**
```
Rate this LINE message on usefulness for an EMBA knowledge base:
0 = social chat, greetings, banter
1 = logistics, coordination, scheduling
2 = useful knowledge (frameworks, concepts, readings, insights)
3 = critical (assignments, deadlines, exams, professor instructions)

Message: "{text}"
Sender: {sender}

Return JSON: {"rating": 0-3, "reason": "...", "suggested_topic": "..."}
```

**Cost:** At 150K messages/month, filtering costs:
- Gemini Flash: 50 tokens in, 30 tokens out per message → ~$0.00003/message → **~$4.50/month** for filtering

---

### R13: 2nd Brain Ingestion Path

**The pipeline:**
```
LINE messages → LGIAP PostgreSQL → AI filter (Gemini Flash)
  → useful messages → format as knowledge entries → POST to corpus.json
  → build_graph.py (daily cron) → concept_index.json → 2nd Brain dashboard
```

**Two approaches:**

**A. Direct file write (simpler, cron-safe):**
```python
# Daily cron job in LGIAP
def push_to_brain():
    useful = get_filtered_messages(since="yesterday")
    for msg in useful:
        entry = format_as_corpus_entry(msg)
        update_corpus(entry)  # calls brain's update_corpus()
    subprocess.run(["python3", "/data/emba-second-brain/build_graph.py"])
```

**B. API push (cleaner, real-time):**
```python
# LGIAP worker pushes to brain API
POST http://localhost:8400/lgiap/ingest
Body: [{entry1}, {entry2}, ...]
```

**Recommendation:** Approach A for MVP (no new endpoints needed). Approach B when LGIAP needs permission control.

---

## 🔧 DEPENDENCY VERSION MATRIX

| Package | Min Version | Verified? | Notes |
|---|---|---|---|
| Python | 3.10 | Check VPS | `line-bot-sdk` requires >= 3.10 |
| `line-bot-sdk` | 3.23.0 | ✅ PyPI | Official, actively maintained |
| FastAPI | 0.110+ | ✅ | Webhook handler |
| Uvicorn | 0.29+ | ✅ | ASGI server |
| Dramatiq | 1.16+ | Check PyPI | Task queue |
| Redis | 7.0+ | Check VPS | Dramatiq broker |
| PostgreSQL | 15+ | Check VPS | pgvector requires >= 12, 15+ recommended |
| pgvector | 0.8.2 | Check VPS | `CREATE EXTENSION vector` |
| TimescaleDB | 2.15+ | Optional | Hypertable for messages |
| bge-m3 | Latest | Check PyPI | Via `sentence-transformers` |
| Gemini SDK | `google-genai` | ✅ | NOT `google-generativeai` (deprecated) |
| Node.js | 20+ | Check VPS | Next.js 15 requires >= 18.17 |
| pnpm | 9+ | Check VPS | Next.js package manager |
| Next.js | 15+ | ✅ | App Router |
| ShadCN UI | Latest | ✅ | Via `npx shadcn@latest` |

**Pre-build verification script:**
```bash
#!/bin/bash
echo "=== VERSION CHECK ==="
python3 --version
node --version
pnpm --version
redis-cli --version
psql --version
python3 -c "from sentence_transformers import SentenceTransformer; print('bge-m3: OK')" 2>&1
python3 -c "import dramatiq; print(f'dramatiq: OK')" 2>&1
echo "=== DONE ==="
```

---

## 🚦 PRE-BUILD CHECKLIST

| # | Item | Status |
|---|---|---|
| 1 | LINE Official Account created + group messaging enabled | 🔴 |
| 2 | LINE channel secret + access token generated | 🔴 |
| 3 | VPS versions verified (Python 3.10+, Node 20+, PG 15+) | 🔴 |
| 4 | Redis installed + running on VPS | 🔴 |
| 5 | pgvector extension available in PG | 🔴 |
| 6 | Gemini API key ready (AIza... format) | 🔴 |
| 7 | `lgiap.sasin.cfoth.ai` DNS record created | 🔴 |
| 8 | Let's Encrypt cert obtained for subdomain | 🔴 |
| 9 | 2nd Brain corpus.json path confirmed accessible | 🔴 |
| 10 | WangchanLION-v3 tested via Ollama (optional, for cost savings) | 🔴 |

---

## 📊 ARCHITECTURE DIAGRAM

```
┌─────────────────────────────────────────────────────────┐
│                    LGIAP SYSTEM                          │
│                                                          │
│  LINE Groups ──→ LINE API ──→ Webhook (FastAPI :8085)   │
│                                   │                      │
│                    ┌──────────────┼──────────────┐       │
│                    ▼              ▼              ▼       │
│              Raw Store     Dramatiq Queue    ACK 200     │
│              (PG)         (Redis)                        │
│                    │              │                      │
│         ┌─────────┼──────┐       │                      │
│         ▼         ▼      ▼       ▼                      │
│     Media DL   Embed   AI Pipe  Filter                   │
│     (GCS)    (bge-m3) (Gemini) (0-3 rating)             │
│         │         │      │       │                       │
│         └────┬────┘      │       │                       │
│              ▼           ▼       ▼                       │
│         PostgreSQL   pgvector  Daily Batch               │
│              │           │       │                       │
│              └─────┬─────┘       │                       │
│                    ▼             ▼                       │
│              Search API    Useful Knowledge              │
│                    │             │                       │
│                    ▼             ▼                       │
│         Next.js Dashboard   2nd Brain                    │
│         (lgiap.sasin.cfoth) corpus.json                  │
│                                       │                  │
│                                       ▼                  │
│                              build_graph.py (cron)       │
│                                       │                  │
│                                       ▼                  │
│                              concept_index.json          │
│                                       │                  │
│                                       ▼                  │
│                              sasin.cfoth.ai/brain        │
└─────────────────────────────────────────────────────────┘
```

---

## 🗓️ UPDATED PHASE ROADMAP

| Phase | Duration | Key Deliverables | Dependencies |
|---|---|---|---|
| **0: Pre-flight** | 2 days | LINE account setup, version check, DNS, SSL | R1, R9, R10 |
| **1: Foundation** | 2 weeks | LINE webhook → PostgreSQL, media download, dedup | R2, R3 |
| **2: Intelligence** | 2 weeks | Daily summaries, embeddings, semantic search, topic clustering | R4, R6, R8 |
| **3: AI Filter + 2nd Brain** | 1 week | Message rating pipeline, corpus.json push, build_graph integration | R11, R12, R13 |
| **4: Dashboard** | 2 weeks | Next.js dashboard, AI chat, timeline replay, file library | Node deps |
| **5: Polish + Deploy** | 1 week | Auth, rate limiting, monitoring, PM2, cron jobs | R10 |
