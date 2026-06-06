# LGIAP — AI Pipeline Design

## Overview

The AI pipeline transforms raw LINE group messages into structured intelligence: summaries, topics, actions, decisions, and a queryable knowledge base.

---

## Pipeline Architecture

```
Raw Messages (PostgreSQL)
  │
  ├──→ [Daily Batch] ──────────────────────────────────┐
  │    ├── Group by day + group_id                     │
  │    ├── Skip already-processed messages             │
  │    └── Feed to analysis chain                       │
  │                                                     │
  ├──→ [Thread Reconstruction] ────────────────────────┤
  │    ├── Embed messages with bge-m3                  │
  │    ├── Agglomerative clustering (cosine similarity) │
  │    ├── OR: LLM-based reply-to prediction           │
  │    └── Output: thread_id per message               │
  │                                                     │
  ├──→ [Topic Clustering] ────────────────────────────┤
  │    ├── BERTopic with bge-m3 embeddings             │
  │    ├── HDBSCAN for dynamic cluster count           │
  │    ├── LLM topic labeling (Gemini Flash)           │
  │    └── Output: topic_id, topic_name per cluster    │
  │                                                     │
  ├──→ [Summarization] ───────────────────────────────┤
  │    ├── Per-thread summary (Gemini Flash)           │
  │    ├── Daily rollup summary                        │
  │    └── Output: summary_text, key_points            │
  │                                                     │
  ├──→ [Extraction] ──────────────────────────────────┤
  │    ├── Action items (Claude Sonnet 4.6)            │
  │    │   └── {owner, task, due_date, source_msg}     │
  │    ├── Decisions (Claude Sonnet 4.6)               │
  │    │   └── {decision, maker, topic, confidence}    │
  │    ├── Assignments (GPT-5.4 mini)                  │
  │    │   └── {title, due_date, class, professor}     │
  │    └── Output: structured records in PG            │
  │                                                     │
  └──→ [Knowledge Graph] ─────────────────────────────┤
       ├── Entity extraction (Gemini Flash)            │
       ├── Relationship extraction                     │
       ├── LightRAG indexing                            │
       └── Output: graph nodes + edges in PG           │
```

---

## Model Selection by Task

### 1. Summarization → Gemini 3.1 Flash

**Why:** 1M token context window fits an entire day's messages from a busy group. $0.50/$3.00 per 1M tokens is the cheapest per-context pricing.

**Prompt template:**
```
You are analyzing LINE group chat messages. Summarize the key discussions.

Group: {group_name}
Date: {date}
Messages: {chronological_messages}

Generate:
1. Main Topics (with timestamps)
2. Key Decisions (who decided what)
3. Action Items (who needs to do what, by when)
4. Shared Resources (files, links, images)
5. Open Questions (unanswered queries, pending items)

Be concise. Use Thai or English based on the original messages.
Cite source message IDs where relevant.
```

### 2. Topic Clustering → BERTopic + bge-m3

**Pipeline:**
```python
from bertopic import BERTopic
from sentence_transformers import SentenceTransformer

# Embed with bge-m3
model = SentenceTransformer("BAAI/bge-m3")
embeddings = model.encode(messages)

# Cluster with BERTopic
topic_model = BERTopic(
    embedding_model=model,
    hdbscan_model=HDBSCAN(min_cluster_size=3, metric='cosine'),
    vectorizer_model=CountVectorizer(stop_words=['ครับ', 'ค่ะ', 'คะ', 'นะ']),  # Thai stopwords
    representation_model="gemini-3.1-flash"  # LLM topic labels
)

topics, probs = topic_model.fit_transform(messages, embeddings)
```

**Why not pure LLM clustering:** BERTopic is deterministic and reproducible. LLM-only clustering changes results each run. HDBSCAN handles variable cluster counts automatically.

### 3. Action Item Extraction → Claude Sonnet 4.6

**Why Claude:** Best at structured extraction from messy conversations. Better at identifying implicit obligations ("I'll try to send it tomorrow" = action item with low confidence).

**Prompt template:**
```
Extract action items from this LINE group conversation.

For each action item, provide:
- owner: WHO is responsible
- task: WHAT needs to be done  
- due_date: WHEN (ISO format, null if unspecified)
- source_message_id: which message contained this
- confidence: HIGH/MEDIUM/LOW

Only extract explicit commitments. Skip casual mentions.

Messages:
{thread_messages}

Output as JSON array.
```

### 4. RAG Q&A → Hybrid Retrieval + Gemini Flash

**Pipeline:**
```
User: "What did Ajarn say about the final presentation?"

1. Embed query with bge-m3
2. pgvector cosine search → top 20 messages
3. PostgreSQL tsquery → Boolean keyword matches
4. Combine + deduplicate → 30 candidates
5. Cohere Rerank 3 → top 5 most relevant
6. Gemini Flash: answer with citations

Response:
"Ajarn mentioned the final presentation on June 5 at 09:12.
Key requirements: PDF format, submit via LMS, due Sunday 18:00.
[Source: June 5 09:12, June 5 09:18]"
```

### 5. Thread Reconstruction

**Approach A: Embedding clustering (fast, less accurate)**
```python
from sklearn.cluster import AgglomerativeClustering
embeddings = model.encode(messages)
clustering = AgglomerativeClustering(
    n_clusters=None, distance_threshold=0.3, metric='cosine'
)
```

**Approach B: LLM-based reply prediction (slow, more accurate)**
```
Given these messages in chronological order, identify
which message each one is replying to. Consider:
- Named mentions
- Topic continuity
- Temporal proximity
- Question-answer patterns

Return: {message_id: reply_to_message_id}
```

**MVP decision:** Start with Approach A. Switch to B only if users report thread confusion.

---

## Cost Calculation (per group, per month)

| Task | Frequency | Tokens/run | Model | Cost/run | Monthly |
|---|---|---|---|---|---|
| Daily summary | 1x/day | 3K in, 500 out | Gemini Flash | $0.0025 | $0.08 |
| Topic labeling | 1x/day | 2K in, 200 out | Gemini Flash | $0.0016 | $0.05 |
| Action extraction | 1x/day | 3K in, 300 out | Claude Sonnet | $0.0135 | $0.40 |
| Decision extraction | 1x/day | 2K in, 200 out | Claude Sonnet | $0.0090 | $0.27 |
| RAG Q&A | 10x/day | 1K in, 200 out | Gemini Flash | $0.0011 | $0.33 |
| Embeddings | per message | 0 tokens | bge-m3 (local) | $0 | $0 |
| **Total per group** | | | | | **~$1.13/mo** |

**For 10 groups:** ~$11/mo in LLM costs. Add ~$5 for storage. Realistic total: **$20-30/mo for MVP**.

---

## Thai Language Strategy

| Priority | Approach | When |
|---|---|---|
| 1 | Gemini 3.1 Flash (best Thai multilingual) | All production tasks |
| 2 | WangchanLION-v3 via Ollama (local) | Batch processing, cost-sensitive |
| 3 | bge-m3 embeddings (proven Thai performance) | All vector operations |

**Code-switching handling:** LINE groups frequently mix Thai + English. Gemini Flash handles this best — Google trained extensively on Southeast Asian code-switching data.

---

## Embedding Strategy

### What to embed:
- ✅ Text messages > 20 characters
- ✅ OCR output from images
- ✅ Audio transcripts
- ✅ Document summaries
- ❌ Stickers (no text to embed)
- ❌ URLs (embed page title/description instead)
- ❌ Reactions (too short)

### Chunking:
- Single messages: embed as-is (avg 50-200 chars)
- Long messages (>2K chars): split by paragraph, embed each, link to parent
- File summaries: embed the AI-generated summary, not the raw file

---

## Quality Assurance

1. **Daily review flag:** Mark summaries with `confidence: LOW` if AI detects ambiguity
2. **User feedback loop:** Thumbs up/down on AI answers → improve reranking
3. **Admin override:** Edit/correct AI-extracted topics, actions, decisions
4. **Source citation always:** Every AI output links to source messages
5. **Hallucination guard:** Prompt instructs "If unsure, say so. Never fabricate."
