"""LGIAP — Message Ingestion + Deduplication + Queue Pipeline"""
import json, logging, requests
from datetime import datetime, timezone
import dramatiq
from app.config import DATABASE_URL, EMBEDDING_API_URL, EMBEDDING_MODEL, GEMINI_API_KEY

logger = logging.getLogger("lgiap.ingest")

# Import after dramatiq broker is set up
from app.tasks import redis_broker

def _get_db():
    """Lazy DB connection"""
    import psycopg2
    return psycopg2.connect(DATABASE_URL)

# Cache for group names (avoid repeated LINE API calls)
_group_name_cache = {}

def _get_group_name(group_id: str) -> str:
    """Fetch group name from LINE API, with in-memory cache."""
    if group_id in _group_name_cache:
        return _group_name_cache[group_id]
    
    from app.config import LINE_CHANNEL_TOKEN
    if LINE_CHANNEL_TOKEN:
        try:
            req = requests.get(
                f"https://api.line.me/v2/bot/group/{group_id}/summary",
                headers={"Authorization": f"Bearer {LINE_CHANNEL_TOKEN}"},
                timeout=5
            )
            if req.status_code == 200:
                name = req.json().get("groupName", group_id)
                _group_name_cache[group_id] = name
                return name
        except Exception:
            pass
    
    _group_name_cache[group_id] = group_id
    return group_id


@dramatiq.actor(max_retries=3, min_backoff=2000, max_backoff=30000)
def queue_message(event_type: str, message_type: str, message_id: str, user_id: str,
                  group_id: str, text: str, timestamp: int, reply_token, raw):
    """Primary ingestion: store message, then chain downstream tasks"""
    conn = _get_db()
    try:
        cur = conn.cursor()
        
        # Dedup: skip if message_id already exists
        cur.execute("SELECT id FROM messages WHERE line_message_id = %s", (message_id,))
        if cur.fetchone():
            logger.debug(f"Dedup: skipping {message_id}")
            return
        
        # Fetch group name from LINE API (cached)
        group_name = _get_group_name(group_id) if group_id else None
        
        # Store raw message
        raw_json = json.dumps(raw) if isinstance(raw, dict) else str(raw)
        ts = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc) if timestamp else datetime.now(timezone.utc)
        
        cur.execute("""
            INSERT INTO messages (line_message_id, group_id, group_name, user_id, message_type, 
                                  text_content, raw_event_json, timestamp, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
        """, (message_id, group_id, group_name, user_id, message_type, text, raw_json, ts))
        msg_id = cur.fetchone()[0]
        conn.commit()
        
        # Chain: AI filter (if text message) → embedding → 2nd Brain
        if message_type == "text" and text:
            filter_message.send(msg_id, text, user_id, group_id)
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Ingest failed for {message_id}: {e}")
        raise
    finally:
        conn.close()

@dramatiq.actor(max_retries=2, min_backoff=5000, max_backoff=60000)
def filter_message(msg_id: int, text: str, user_id: str, group_id: str):
    """AI Filter: Rate message 0-3. Only 2+ get embedded and sent to 2nd Brain."""
    if not GEMINI_API_KEY:
        logger.warning("No Gemini API key — skipping AI filter")
        return
    
    rating, reason, topic = _rate_message(text, user_id)
    logger.info(f"Filter: msg={msg_id} rating={rating} topic={topic}")
    
    # Store rating
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE messages SET ai_rating = %s, ai_topic = %s WHERE id = %s",
                    (rating, topic, msg_id))
        conn.commit()
    finally:
        conn.close()
    
    if rating >= 2:
        # Useful knowledge — embed and push to 2nd Brain
        embed_message.send(msg_id, text)
        push_to_brain.send(msg_id, text, user_id, group_id, topic, rating)

@dramatiq.actor(max_retries=2, min_backoff=5000)
def embed_message(msg_id: int, text: str):
    """Generate bge-m3 embedding via Ginnie's VPS (Ollama tunnel), fallback to Gemini"""
    embedding = None
    
    # Try Ginnie first
    try:
        resp = requests.post(EMBEDDING_API_URL, 
                           json={"model": EMBEDDING_MODEL, "input": text},
                           timeout=5)  # short timeout — fail fast to fallback
        data = resp.json()
        embedding = data.get("embeddings", [[]])[0]
    except Exception:
        pass  # Ginnie down → try Gemini fallback
    
    # Fallback: Gemini embeddings API
    if not embedding and GEMINI_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.embed_content(
                model="text-embedding-004",
                contents=[text],
            )
            embedding = resp.embeddings[0].values if resp.embeddings else None
        except Exception as e:
            logger.warning(f"Gemini embed fallback also failed: {e}")
    
    if embedding:
        conn = _get_db()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE messages SET embedding = %s::vector WHERE id = %s",
                       (embedding, msg_id))
            conn.commit()
        finally:
            conn.close()

@dramatiq.actor(max_retries=2, min_backoff=10000)
def push_to_brain(msg_id: int, text: str, user_id: str, group_id: str, topic: str, rating: int):
    """Push useful knowledge to 2nd Brain corpus.json"""
    import os
    from pathlib import Path
    from app.config import BRAIN_CORPUS_PATH
    
    try:
        entry = {
            "drive_id": f"line_{msg_id}",
            "source_folder": f"LINE/{group_id or 'unknown'}",
            "name": f"line_msg_{msg_id}.txt",
            "title": topic or "LINE Group Knowledge",
            "summary": text[:500],
            "frameworks": [],
            "topics": [topic] if topic else ["General"],
            "key_concepts": [],
            "difficulty": "foundational",
            "reading_time_min": 1,
            "tags": ["LINE", f"rating_{rating}"],
            "content": text,
            "size": len(text),
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "modified": datetime.now(timezone.utc).isoformat(),
            "md5": "",
        }
        
        # Update corpus.json (upsert by drive_id)
        corpus_path = BRAIN_CORPUS_PATH
        if corpus_path.exists():
            corpus = json.loads(corpus_path.read_text())
            # Remove old entry with same drive_id
            corpus = [e for e in corpus if e.get("drive_id") != entry["drive_id"]]
            corpus.append(entry)
            corpus_path.write_text(json.dumps(corpus, indent=2, ensure_ascii=False))
            logger.info(f"2nd Brain: pushed msg {msg_id} (rating={rating}, topic={topic})")
    except Exception as e:
        logger.error(f"2nd Brain push failed for msg {msg_id}: {e}")


def _rate_message(text: str, user_id: str) -> tuple:
    """Rate message usefulness 0-3 using Gemini Flash"""
    import google.genai as genai
    import re
    
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""Rate this LINE group message on usefulness for an EMBA knowledge base:
0 = social chat, greetings, banter, stickers, reactions
1 = logistics, coordination, scheduling, "where is class"
2 = useful knowledge (frameworks, concepts, readings, insights, tips)
3 = critical (assignments, deadlines, exams, professor instructions, important decisions)

Message: "{text[:500]}"
Sender: {user_id}

Return ONLY a valid JSON object (no markdown, no backticks): {{"rating": 0,"reason":"brief","suggested_topic":"short topic"}}"""
    
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"temperature": 0.1, "maxOutputTokens": 512},
        )
        raw = resp.text.strip()
        
        # Clean markdown fences
        raw = raw.replace("```json", "").replace("```", "").strip()
        
        # Try direct JSON parse
        try:
            data = json.loads(raw)
            return data.get("rating", 0), data.get("reason", ""), data.get("suggested_topic", "")
        except json.JSONDecodeError:
            pass
        
        # Fallback: extract JSON object with regex
        match = re.search(r'\{[^{}]*"rating"\s*:\s*(\d)[^{}]*\}', raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                return data.get("rating", 0), data.get("reason", ""), data.get("suggested_topic", "")
            except json.JSONDecodeError:
                pass
        
        # Last resort: extract just the rating number from raw text
        rating_match = re.search(r'"rating"\s*:\s*(\d)', raw)
        if rating_match:
            rating = int(rating_match.group(1))
            return rating, "extracted from partial JSON", ""
        
        logger.warning(f"AI filter: could not parse Gemini response: {raw[:100]}")
        return 0, f"parse error: {raw[:80]}", ""
        
    except Exception as e:
        logger.error(f"AI filter failed: {e}")
        return 0, str(e), ""
