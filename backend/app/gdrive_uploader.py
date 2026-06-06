"""LGIAP Google Drive Uploader — per-group folders: images/, videos/, docs/"""
import os, sys, logging, mimetypes, json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import DATABASE_URL
import psycopg2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lgiap.gdrive")

GOOGLE_KEY_PATH = "/data/lgiap/google-key.json"
ROOT_FOLDER_ID = "1-Ba7sE0FaL4xymUv7YjAcmc_uipFQOOU"  # User's shared LGIAP folder

def _get_drive_service():
    """Create Google Drive service — OAuth (user account) or Service Account fallback."""
    from google.oauth2.credentials import Credentials
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    
    # Try OAuth token first
    token_path = "/data/lgiap/oauth_token.json"
    if os.path.exists(token_path):
        with open(token_path) as f:
            token_data = json.load(f)
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data["refresh_token"],
            client_id=token_data["client_id"],
            client_secret=token_data["client_secret"],
            token_uri="https://oauth2.googleapis.com/token",
            scopes=["https://www.googleapis.com/auth/drive.file"]
        )
        logger.info("Using OAuth (user account)")
        return build("drive", "v3", credentials=creds)
    
    # Fallback to service account
    if os.path.exists(GOOGLE_KEY_PATH):
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_KEY_PATH, scopes=["https://www.googleapis.com/auth/drive"]
        )
        logger.info("Using Service Account (limited)")
        return build("drive", "v3", credentials=creds)
    
    logger.warning("No Google credentials found")
    return None


def _find_or_create_folder(service, name: str, parent_id: str = None, shared_drive_id: str = None) -> str:
    """Find a folder by name under parent, or create it. Returns folder ID."""
    # Search existing
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    
    kwargs = {"q": q, "fields": "files(id,name)", "pageSize": 5}
    if shared_drive_id:
        kwargs["driveId"] = shared_drive_id
        kwargs["corpora"] = "drive"
        kwargs["includeItemsFromAllDrives"] = True
        kwargs["supportsAllDrives"] = True
    
    results = service.files().list(**kwargs).execute()
    files = results.get("files", [])
    if files:
        logger.debug(f"  Found existing folder: {name} ({files[0]['id']})")
        return files[0]["id"]
    
    # Create new
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    
    create_kwargs = {"body": meta, "fields": "id,name"}
    if shared_drive_id:
        create_kwargs["supportsAllDrives"] = True
    
    folder = service.files().create(**create_kwargs).execute()
    logger.info(f"  ✅ Created folder: {name} ({folder['id']})")
    return folder["id"]


def ensure_folder_structure(group_name: str) -> dict:
    """Ensure per-group subfolders inside the shared LGIAP root folder."""
    service = _get_drive_service()
    if not service:
        return {}
    
    safe_name = group_name.replace("/", "_").replace("\\", "_")[:100]
    
    # Find or create group folder under the shared root
    group_id = _find_or_create_folder(service, safe_name, ROOT_FOLDER_ID)
    images_id = _find_or_create_folder(service, "images", group_id)
    videos_id = _find_or_create_folder(service, "videos", group_id)
    docs_id = _find_or_create_folder(service, "docs", group_id)
    
    return {
        "root": ROOT_FOLDER_ID,
        "group": group_id,
        "images": images_id,
        "videos": videos_id,
        "docs": docs_id,
    }


def _get_folder_for_type(folders: dict, media_type: str) -> str:
    """Map media type to the correct sub-folder ID."""
    if media_type == "image":
        return folders.get("images", "")
    elif media_type == "video":
        return folders.get("videos", "")
    else:
        return folders.get("docs", "")


def upload_to_drive(local_path: str, media_type: str, group_name: str = "Default") -> dict:
    """Upload a file to the correct per-group sub-folder on Google Drive."""
    service = _get_drive_service()
    if not service:
        return {"error": "Drive not configured"}
    
    from googleapiclient.http import MediaFileUpload
    
    # Ensure folder structure exists
    folders = ensure_folder_structure(group_name)
    target_folder = _get_folder_for_type(folders, media_type)
    
    if not target_folder:
        return {"error": f"No target folder for type {media_type}"}
    
    filename = os.path.basename(local_path)
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    
    file_metadata = {
        "name": filename,
        "parents": [target_folder],
    }
    
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
    
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink, webContentLink, size, name",
    ).execute()
    
    # Make publicly viewable
    service.permissions().create(
        fileId=file["id"],
        body={"type": "anyone", "role": "reader"},
    ).execute()
    
    logger.info(f"  📤 {filename} → Drive/{group_name}/{media_type}s/ ({int(file.get('size',0))/1024:.0f}KB)")
    
    # Generate thumbnail link
    thumb_link = f"https://drive.google.com/thumbnail?id={file['id']}&sz=w400"
    view_link = file.get("webViewLink", "")
    
    # For images: use thumbnail as the display URL; for videos: use view link
    display_url = thumb_link if media_type == "image" else view_link
    
    return {
        "drive_id": file["id"],
        "view_link": view_link,
        "thumbnail_link": thumb_link,
        "download_link": file.get("webContentLink", ""),
        "display_url": display_url,
        "size": file.get("size", 0),
        "folder": f"{group_name}/{media_type}s",
    }


def upload_pending_to_drive():
    """Find locally-stored media without Drive links, upload to per-group folders."""
    if not os.path.exists(GOOGLE_KEY_PATH):
        logger.info("No Google Drive key — skipping Drive upload")
        return 0
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Find downloaded files without Drive links, with group info
    cur.execute("""
        SELECT mf.id, mf.message_id, mf.media_type, mf.file_path, 
               COALESCE(m.group_name, m.group_id, 'Default') as group_name
        FROM media_files mf
        JOIN messages m ON mf.message_id = m.id
        WHERE mf.download_status = 'downloaded'
        AND mf.file_path IS NOT NULL
        AND mf.file_path LIKE '/data/lgiap/media/%'
        AND mf.id NOT IN (
            SELECT media_file_id FROM media_drive_links
        )
        ORDER BY mf.id
    """)
    pending = cur.fetchall()
    
    if not pending:
        logger.info("No media pending Drive upload")
        conn.close()
        return 0
    
    logger.info(f"Uploading {len(pending)} files to Google Drive (per-group folders)...")
    uploaded = 0
    
    for mf_id, msg_id, mtype, filepath, group_name in pending:
        if not os.path.exists(filepath):
            logger.warning(f"  #{mf_id}: file missing {filepath}")
            continue
        
        try:
            result = upload_to_drive(filepath, mtype, group_name)
            
            if "error" in result:
                logger.info(f"  #{mf_id} [{mtype}]: {result['error']}")
                continue
            
            # Store Drive link (with thumbnail for images)
            display_url = result.get("display_url", result["view_link"])
            cur.execute("""
                INSERT INTO media_drive_links (media_file_id, drive_id, view_link, download_link, thumbnail_link, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (media_file_id) DO UPDATE
                SET drive_id = EXCLUDED.drive_id, view_link = EXCLUDED.view_link,
                    download_link = EXCLUDED.download_link, thumbnail_link = EXCLUDED.thumbnail_link,
                    uploaded_at = NOW()
            """, (mf_id, result["drive_id"], result["view_link"], result["download_link"], result.get("thumbnail_link", "")))
            
            # Update message content_url to Drive view link (dashboard extracts ID for thumbnail)
            cur.execute("UPDATE messages SET content_url = %s WHERE id = %s",
                        (result["view_link"], msg_id))
            
            uploaded += 1
            
        except Exception as e:
            logger.error(f"  #{mf_id} [{mtype}]: {e}")
    
    conn.commit()
    conn.close()
    logger.info(f"✅ Uploaded {uploaded}/{len(pending)} to Google Drive")
    return uploaded
