"""LGIAP Media Downloader — downloads image/video/audio/files from LINE Content API"""
import os, sys, logging, requests
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import DATABASE_URL, LINE_CHANNEL_TOKEN as LINE_CHANNEL_ACCESS_TOKEN
import psycopg2

logger = logging.getLogger("lgiap.media")

MEDIA_ROOT = "/data/lgiap/media"
os.makedirs(MEDIA_ROOT, exist_ok=True)

MIME_TO_EXT = {
    # Images
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
    "image/svg+xml": ".svg", "image/bmp": ".bmp", "image/tiff": ".tiff",
    # Videos
    "video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-msvideo": ".avi",
    "video/webm": ".webm", "video/x-matroska": ".mkv",
    # Audio
    "audio/mp4": ".m4a", "audio/mpeg": ".mp3", "audio/ogg": ".ogg",
    "audio/wav": ".wav", "audio/aac": ".aac", "audio/flac": ".flac",
    # Documents
    "text/plain": ".txt", "text/csv": ".csv", "text/html": ".html",
    "text/markdown": ".md", "text/x-python": ".py", "text/javascript": ".js",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/zip": ".zip", "application/gzip": ".gz",
    "application/x-7z-compressed": ".7z", "application/x-rar-compressed": ".rar",
    "application/json": ".json", "application/xml": ".xml",
}

def _get_db():
    return psycopg2.connect(DATABASE_URL)

def download_pending_media():
    """Download all media files that haven't been fetched yet."""
    conn = _get_db()
    cur = conn.cursor()
    
    # Find messages with media that need downloading
    cur.execute("""
        SELECT m.id, m.message_type, m.raw_event_json->'message'->>'id' as line_msg_id,
               m.raw_event_json->'message'->>'fileName' as original_name
        FROM messages m
        LEFT JOIN media_files mf ON mf.message_id = m.id
        WHERE m.message_type IN ('image','video','audio','file')
        AND mf.id IS NULL
        ORDER BY m.id
    """)
    pending = cur.fetchall()
    
    if not pending:
        logger.info("No media to download")
        conn.close()
        return 0
    
    logger.info(f"Downloading {len(pending)} media files...")
    downloaded = 0
    
    for msg_id, mtype, line_msg_id, original_name in pending:
        if not line_msg_id:
            cur.execute("""
                INSERT INTO media_files (message_id, line_message_id, media_type, download_status, error_message)
                VALUES (%s, %s, %s, 'failed', 'No LINE message ID')
            """, (msg_id, 'unknown', mtype))
            continue
        
        # Check if already attempted
        cur.execute("SELECT id, download_status, download_attempts FROM media_files WHERE message_id=%s AND line_message_id=%s",
                    (msg_id, line_msg_id))
        existing = cur.fetchone()
        if existing and existing[1] == 'downloaded':
            logger.info(f"  #{msg_id}: already downloaded, skipping")
            continue
        
        if existing and existing[2] >= 3:
            logger.info(f"  #{msg_id}: max attempts reached ({existing[2]}), skipping")
            continue
        
        try:
            success = _download_single(cur, msg_id, mtype, line_msg_id, original_name)
            if success:
                downloaded += 1
        except Exception as e:
            logger.error(f"  #{msg_id} [{mtype}]: {e}")
            cur.execute("""
                INSERT INTO media_files (message_id, line_message_id, media_type, download_status, error_message, download_attempts, last_attempt_at)
                VALUES (%s, %s, %s, 'failed', %s, 1, NOW())
                ON CONFLICT DO NOTHING
            """, (msg_id, line_msg_id, mtype, str(e)[:500]))
    
    conn.commit()
    conn.close()
    logger.info(f"✅ Downloaded {downloaded}/{len(pending)} media files")
    return downloaded


def _download_single(cur, msg_id, mtype, line_msg_id, original_name=None):
    """Download a single media file from LINE Content API."""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        logger.warning(f"  #{msg_id}: No LINE_CHANNEL_ACCESS_TOKEN configured")
        return False
    
    url = f"https://api-data.line.me/v2/bot/message/{line_msg_id}/content"
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
    
    logger.info(f"  #{msg_id} [{mtype}]: Downloading {line_msg_id}...")
    if original_name:
        logger.info(f"    Original filename: {original_name}")
    
    resp = requests.get(url, headers=headers, timeout=60, stream=True)
    
    if resp.status_code != 200:
        error = resp.text[:200]
        logger.error(f"  #{msg_id}: HTTP {resp.status_code}: {error}")
        cur.execute("""
            INSERT INTO media_files (message_id, line_message_id, media_type, download_status, error_message, download_attempts, last_attempt_at)
            VALUES (%s, %s, %s, 'failed', %s, 1, NOW())
            ON CONFLICT DO NOTHING
        """, (msg_id, line_msg_id, mtype, f"HTTP {resp.status_code}: {error}"))
        return False
    
    # Determine extension: 1) MIME type map  2) original filename extension  3) .bin
    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
    ext = MIME_TO_EXT.get(content_type)
    
    if not ext and original_name:
        # Fallback: use original filename extension
        if "." in original_name:
            ext = os.path.splitext(original_name)[1].lower()
            logger.info(f"    Using original extension: {ext}")
    
    if not ext:
        ext = ".bin"
        logger.warning(f"    Unknown MIME type '{content_type}', falling back to .bin")
    
    filename = f"{msg_id}_{mtype}{ext}"
    filepath = os.path.join(MEDIA_ROOT, filename)
    
    # Save to disk
    total_size = 0
    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            total_size += len(chunk)
    
    # Record in DB
    cur.execute("""
        INSERT INTO media_files 
        (message_id, line_message_id, media_type, file_path, file_size_bytes, mime_type, download_status, downloaded_at)
        VALUES (%s, %s, %s, %s, %s, %s, 'downloaded', NOW())
        ON CONFLICT DO NOTHING
    """, (msg_id, line_msg_id, mtype, filepath, total_size, content_type))
    
    # Update message's content_url
    cur.execute("UPDATE messages SET content_url = %s WHERE id = %s", (filepath, msg_id))
    
    logger.info(f"  #{msg_id} ✅ Downloaded: {filename} ({total_size/1024:.1f} KB, {content_type})")
    return True
