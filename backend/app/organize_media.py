"""LGIAP Local Media Organizer — per-group folder structure on disk"""
import os, sys, shutil, logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import DATABASE_URL
import psycopg2

logger = logging.getLogger("lgiap.organizer")

MEDIA_ROOT = "/data/lgiap/media"

def organize_media():
    """Move media files into per-group subfolders: {group}/images/, {group}/videos/"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Find media files at root level (not yet in group subfolders)
    cur.execute("""
        SELECT mf.id, mf.file_path, mf.media_type,
               COALESCE(m.group_name, m.group_id, 'Default') as group_name
        FROM media_files mf
        JOIN messages m ON mf.message_id = m.id
        WHERE mf.download_status = 'downloaded'
        AND mf.file_path LIKE '/data/lgiap/media/%'
        AND mf.file_path NOT LIKE '/data/lgiap/media/%/%'
    """)
    pending = cur.fetchall()
    
    if not pending:
        logger.info("All media already organized")
        conn.close()
        return 0
    
    logger.info(f"Organizing {len(pending)} files into per-group folders...")
    moved = 0
    
    for mf_id, old_path, mtype, group_name in pending:
        safe_group = group_name.replace("/", "_").replace("\\", "_").strip()[:50]
        folder_type = "images" if mtype == "image" else "videos" if mtype == "video" else "docs"
        
        # Create: /data/lgiap/media/{Group}/images/
        group_dir = os.path.join(MEDIA_ROOT, safe_group, folder_type)
        os.makedirs(group_dir, exist_ok=True)
        
        filename = os.path.basename(old_path)
        new_path = os.path.join(group_dir, filename)
        
        if os.path.exists(old_path) and old_path != new_path:
            shutil.move(old_path, new_path)
            cur.execute("UPDATE media_files SET file_path = %s WHERE id = %s", (new_path, mf_id))
            cur.execute("UPDATE messages SET content_url = %s WHERE id = (SELECT message_id FROM media_files WHERE id = %s)",
                        (f"/media/{safe_group}/{folder_type}/{filename}", mf_id))
            moved += 1
            logger.info(f"  {old_path.split('/')[-1]} → {safe_group}/{folder_type}/")
    
    conn.commit()
    conn.close()
    logger.info(f"✅ Moved {moved} files")
    return moved


def get_structure_summary():
    """Show the full media folder structure."""
    if not os.path.exists(MEDIA_ROOT):
        return "No media yet"
    
    lines = []
    for group in sorted(os.listdir(MEDIA_ROOT)):
        group_path = os.path.join(MEDIA_ROOT, group)
        if not os.path.isdir(group_path):
            continue
        for sub in sorted(os.listdir(group_path)):
            sub_path = os.path.join(group_path, sub)
            if os.path.isdir(sub_path):
                files = [f for f in os.listdir(sub_path) if os.path.isfile(os.path.join(sub_path, f))]
                total = sum(os.path.getsize(os.path.join(sub_path, f)) for f in files)
                lines.append(f"  📁 {group}/{sub}/ — {len(files)} files ({total/1024:.0f} KB)")
    return "\n".join(lines) if lines else "Empty structure"
