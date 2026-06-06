"""LGIAP Periodic Analyzer — rates messages + assigns conversation threads every 5 min"""
import sys, os, json, re, logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import DATABASE_URL, GEMINI_API_KEY
import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("lgiap.analyzer")

def _get_db():
    return psycopg2.connect(DATABASE_URL)

# ============================================================
# PHASE 1: Rate unrated messages
# ============================================================

def rate_unrated_messages():
    """Rate all messages that haven't been rated yet."""
    conn = _get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT id, message_type, text_content, user_id 
        FROM messages WHERE ai_rating = -1
        ORDER BY id
    """)
    unrated = cur.fetchall()
    
    if not unrated:
        logger.info("No unrated messages")
        conn.close()
        return
    
    logger.info(f"Rating {len(unrated)} unrated messages...")
    
    for mid, mtype, text, uid in unrated:
        if mtype == "text" and text:
            # Use AI for text messages
            rating, reason, topic = _rate_with_gemini(text, uid)
        else:
            # Auto-rate non-text as social (0)
            rating, reason, topic = 0, f"auto: {mtype}", ""
        
        cur.execute("UPDATE messages SET ai_rating=%s, ai_topic=%s WHERE id=%s",
                    (rating, topic, mid))
        logger.info(f"  #{mid} [{mtype}] => rating={rating} topic={topic}")
    
    conn.commit()
    conn.close()
    logger.info(f"✅ Rated {len(unrated)} messages")

def _rate_with_gemini(text: str, user_id: str):
    """Rate a text message using Gemini (robust parsing)."""
    if not GEMINI_API_KEY:
        return 0, "no API key", ""
    
    try:
        import google.genai as genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        prompt = f"""Rate this LINE group message on usefulness for an EMBA knowledge base:
0 = social chat, greetings, banter, stickers, reactions
1 = logistics, coordination, scheduling
2 = useful knowledge (frameworks, concepts, readings, insights, tips)
3 = critical (assignments, deadlines, exams, professor instructions, important decisions)

Message: "{text[:500]}"
Sender: {user_id}

Return ONLY a valid JSON (no markdown): {{"rating":0,"reason":"brief","suggested_topic":"short topic"}}"""
        
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"temperature": 0.1, "maxOutputTokens": 512},
        )
        raw = resp.text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        
        # Try direct parse
        try:
            data = json.loads(raw)
            return data.get("rating", 0), data.get("reason", ""), data.get("suggested_topic", "")
        except json.JSONDecodeError:
            pass
        
        # Regex fallback
        match = re.search(r'\{[^{}]*"rating"\s*:\s*(\d)[^{}]*\}', raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                return data.get("rating", 0), data.get("reason", ""), data.get("suggested_topic", "")
            except:
                pass
        
        # Extract just rating number
        rm = re.search(r'"rating"\s*:\s*(\d)', raw)
        if rm:
            return int(rm.group(1)), "extracted", ""
        
        return 0, "parse failed", ""
    except Exception as e:
        logger.error(f"Gemini rating failed: {e}")
        return 0, str(e), ""


# ============================================================
# PHASE 2: Assign conversation threads
# ============================================================

def assign_threads():
    """Group recent messages into conversation threads by time proximity."""
    conn = _get_db()
    cur = conn.cursor()
    
    # Get unthreaded messages from last 24h, ordered by time
    cur.execute("""
        SELECT id, group_id, user_id, text_content, message_type, timestamp, ai_topic
        FROM messages 
        WHERE thread_id IS NULL 
          AND timestamp > NOW() - INTERVAL '24 hours'
        ORDER BY group_id, timestamp
    """)
    messages = cur.fetchall()
    
    if not messages:
        logger.info("No unthreaded messages")
        conn.close()
        return
    
    logger.info(f"Threading {len(messages)} messages...")
    
    # Simple algorithm: group by time gaps > 15 minutes
    THREAD_GAP_MINUTES = 15
    
    threads_created = 0
    messages_assigned = 0
    
    # Group by group_id first
    by_group = defaultdict(list)
    for m in messages:
        by_group[m[1]].append(m)
    
    for group_id, group_msgs in by_group.items():
        current_thread_msgs = []
        last_ts = None
        
        for msg in group_msgs:
            mid, gid, uid, text, mtype, ts, topic = msg
            
            if last_ts is None:
                current_thread_msgs.append(msg)
                last_ts = ts
            elif (ts - last_ts).total_seconds() < THREAD_GAP_MINUTES * 60:
                # Same thread
                current_thread_msgs.append(msg)
                last_ts = ts
            else:
                # Gap > 15 min — close current thread and start new
                _save_thread(cur, group_id, current_thread_msgs)
                threads_created += 1
                messages_assigned += len(current_thread_msgs)
                current_thread_msgs = [msg]
                last_ts = ts
        
        # Save last thread
        if current_thread_msgs:
            _save_thread(cur, group_id, current_thread_msgs)
            threads_created += 1
            messages_assigned += len(current_thread_msgs)
    
    conn.commit()
    conn.close()
    logger.info(f"✅ Created {threads_created} threads, assigned {messages_assigned} messages")


def _save_thread(cur, group_id, messages):
    """Create a conversation thread and assign messages to it."""
    if not messages:
        return
    
    # Generate title from first text message
    title = "Conversation"
    topic = ""
    all_text = []
    for m in messages:
        if m[3] and m[4] == "text":
            all_text.append(m[3])
            if not topic and m[6]:
                topic = m[6]
    
    if all_text:
        title = all_text[0][:80]
    
    started = messages[0][5]
    ended = messages[-1][5]
    
    # Create thread
    cur.execute("""
        INSERT INTO conversation_threads (group_id, title, topic, message_count, started_at, last_message_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (group_id, title, topic, len(messages), started, ended))
    thread_id = cur.fetchone()[0]
    
    # Assign messages to thread
    for m in messages:
        cur.execute("UPDATE messages SET thread_id = %s WHERE id = %s", (thread_id, m[0]))


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    logger.info("=== LGIAP Analyzer Run ===")
    from app.media_downloader import download_pending_media
    from app.gdrive_uploader import upload_pending_to_drive
    from app.profile_sync import sync_profiles
    
    download_pending_media()   # Step 0: fetch any unfetched media from LINE
    upload_pending_to_drive()  # Step 0.5: upload to Google Drive
    sync_profiles()            # Step 0.7: fetch LINE user profiles
    rate_unrated_messages()    # Step 1: rate unrated messages
    assign_threads()           # Step 2: thread assignment
    logger.info("=== Analyzer Complete ===")
