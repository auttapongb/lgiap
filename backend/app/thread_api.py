"""LGIAP — Thread Detection API (Gemini-powered conversation linking)"""
import json
from fastapi import APIRouter
import psycopg2
from app.config import DATABASE_URL, GEMINI_API_KEY

router = APIRouter(prefix="/api")

def _get_db():
    return psycopg2.connect(DATABASE_URL)

@router.get("/thread/{msg_id}")
async def find_thread(msg_id: int):
    """Find messages related to this message using AI analysis"""
    conn = _get_db()
    cur = conn.cursor()
    
    # Get the seed message
    cur.execute("SELECT id, group_id, user_id, message_type, text_content, timestamp FROM messages WHERE id = %s", (msg_id,))
    seed = cur.fetchone()
    if not seed:
        conn.close()
        return {"error": "Message not found", "related_count": 0, "messages": [], "seed_text": ""}
    
    seed_id, group_id, seed_user, seed_type, seed_text, seed_time = seed
    seed_display = seed_text or f"[{seed_type}]"
    
    if not seed_text:
        conn.close()
        return {"error": "Only text messages can be analyzed for threads (for now)", "related_count": 0, "messages": [], "seed_text": seed_display}
    
    # Get nearby messages (1 hour window, same group)
    cur.execute("""
        SELECT id, user_id, message_type, text_content, timestamp 
        FROM messages 
        WHERE group_id = %s 
          AND timestamp BETWEEN %s - INTERVAL '1 hour' AND %s + INTERVAL '1 hour'
          AND message_type = 'text' AND text_content != ''
        ORDER BY timestamp
    """, (group_id, seed_time, seed_time))
    candidates = [(r[0], r[1], r[2], r[3], r[4]) for r in cur.fetchall()]
    conn.close()
    
    if len(candidates) <= 1:
        return {"error": "No other messages in this time window", "related_count": 1, "messages": [{"id": seed_id, "user": seed_user, "type": seed_type, "text": seed_display, "time": str(seed_time)[:19], "relevance": 1.0}], "seed_text": seed_display}
    
    # Use Gemini to find related messages
    if not GEMINI_API_KEY:
        return {"error": "Gemini API key not configured", "related_count": len(candidates), "messages": [], "seed_text": seed_display}
    
    # Build context for Gemini
    lines = []
    for cid, uid, mtype, text, ts in candidates:
        time_label = str(ts)[11:19]
        lines.append(f"[{time_label}] {uid[:8]}: {text[:200]}")
    
    context = "\n".join(lines)
    
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        prompt = f"""Analyze this LINE group conversation and find messages that are part of the SAME conversation thread as the seed message.

SEED MESSAGE: "[{str(seed_time)[11:19]}] {seed_user[:8]}: {seed_text[:200]}"

ALL MESSAGES IN TIME WINDOW:
{context}

Return a JSON object with:
- "related_ids": list of message IDs (from the time labels) that are in the SAME conversation thread as the seed
- "summary": a 1-2 sentence summary of what this conversation thread is about

Consider: topic continuity, question-answer pairs, mentions, temporal proximity. Messages about different topics should NOT be included.

Return ONLY JSON, no markdown formatting."""
        
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"temperature": 0.1, "maxOutputTokens": 500},
        )
        raw = resp.text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        
        related_ids = result.get("related_ids", [])
        summary = result.get("summary", "")
        
        # Build response with full message data
        time_index = {}
        for cid, uid, mtype, text, ts in candidates:
            time_index[str(ts)[11:19]] = {
                "id": cid, "user": uid, "type": mtype, "text": text, "time": str(ts)[:19]
            }
        
        messages_out = []
        for rid in related_ids:
            if rid in time_index:
                entry = time_index[rid]
                entry["relevance"] = 1.0 if rid == seed_id else 0.8
                messages_out.append(entry)
        
        # Add seed if not in results
        if not any(m["id"] == seed_id for m in messages_out):
            messages_out.insert(0, {"id": seed_id, "user": seed_user, "type": seed_type, "text": seed_display, "time": str(seed_time)[:19], "relevance": 1.0})
        
        return {
            "related_count": len(messages_out),
            "seed_text": seed_display,
            "ai_summary": summary,
            "messages": messages_out
        }
        
    except Exception as e:
        return {"error": f"AI analysis failed: {str(e)[:100]}", "related_count": len(candidates), "messages": [], "seed_text": seed_display}
