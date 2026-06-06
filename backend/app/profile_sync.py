"""LGIAP Profile Sync — fetches LINE user profiles (name + avatar)"""
import os, sys, logging, requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import DATABASE_URL, LINE_CHANNEL_TOKEN
import psycopg2

logger = logging.getLogger("lgiap.profiles")

def sync_profiles():
    """Fetch display names + profile pictures for users without them."""
    if not LINE_CHANNEL_TOKEN:
        logger.warning("No LINE_CHANNEL_TOKEN configured")
        return 0
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Find users without profiles (exclude 'system', empty, None)
    cur.execute("""
        SELECT DISTINCT m.user_id, m.group_id 
        FROM messages m
        LEFT JOIN profiles p ON p.user_id = m.user_id
        WHERE m.user_id IS NOT NULL 
          AND m.user_id != ''
          AND m.user_id != 'system'
          AND p.user_id IS NULL
        LIMIT 20
    """)
    pending = cur.fetchall()
    
    if not pending:
        logger.info("No users need profile sync")
        conn.close()
        return 0
    
    logger.info(f"Syncing profiles for {len(pending)} users...")
    synced = 0
    
    for user_id, group_id in pending:
        try:
            # Try group member endpoint first (best profile data)
            url = f"https://api.line.me/v2/bot/group/{group_id}/member/{user_id}"
            headers = {"Authorization": f"Bearer {LINE_CHANNEL_TOKEN}"}
            resp = requests.get(url, headers=headers, timeout=10)
            
            data = resp.json() if resp.status_code == 200 else None
            
            if not data or "displayName" not in data:
                # Fallback: general profile endpoint
                url = f"https://api.line.me/v2/bot/profile/{user_id}"
                resp = requests.get(url, headers=headers, timeout=10)
                data = resp.json() if resp.status_code == 200 else None
            
            if data and "displayName" in data:
                name = data.get("displayName", user_id)
                pic = data.get("pictureUrl", "")
                
                cur.execute("""
                    INSERT INTO profiles (user_id, display_name, picture_url, group_id, last_synced_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id) DO UPDATE
                    SET display_name = EXCLUDED.display_name,
                        picture_url = EXCLUDED.picture_url,
                        last_synced_at = NOW()
                """, (user_id, name, pic, group_id))
                
                logger.info(f"  {user_id[:12]}... → {name} {'🖼' if pic else '⚫ no pic'}")
                synced += 1
            else:
                # Store with fallback name
                cur.execute("""
                    INSERT INTO profiles (user_id, display_name, picture_url, group_id)
                    VALUES (%s, %s, '', %s)
                    ON CONFLICT DO NOTHING
                """, (user_id, f"User_{user_id[:8]}", group_id))
                logger.info(f"  {user_id[:12]}... → (no profile data)")
                
        except Exception as e:
            logger.error(f"  {user_id[:12]}... → error: {e}")
    
    conn.commit()
    conn.close()
    logger.info(f"✅ Synced {synced} profiles")
    return synced
