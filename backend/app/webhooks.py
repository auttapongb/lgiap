"""LGIAP — LINE Webhook Handler"""
import json, logging
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent, VideoMessageContent, AudioMessageContent, FileMessageContent, StickerMessageContent, JoinEvent, LeaveEvent, MemberJoinedEvent, MemberLeftEvent, UnsendEvent

from app.config import LINE_CHANNEL_SECRET, LINE_CHANNEL_TOKEN
from app.tasks.ingest import queue_message

logger = logging.getLogger("lgiap.webhook")
router = APIRouter()

handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ─── Event Handlers ───────────────────────────────

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    queue_message.send(
        event_type="message",
        message_type="text",
        message_id=event.message.id,
        user_id=event.source.user_id,
        group_id=event.source.group_id if hasattr(event.source, 'group_id') else None,
        text=event.message.text,
        timestamp=event.timestamp,
        reply_token=event.reply_token,
        raw=event.to_dict() if hasattr(event, 'to_dict') else str(event),
    )

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    queue_message.send("message", "image", event.message.id, event.source.user_id, getattr(event.source, 'group_id', None), "", event.timestamp, event.reply_token, event.to_dict())

@handler.add(MessageEvent, message=VideoMessageContent)
def handle_video(event):
    queue_message.send("message", "video", event.message.id, event.source.user_id, getattr(event.source, 'group_id', None), "", event.timestamp, event.reply_token, event.to_dict())

@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio(event):
    queue_message.send("message", "audio", event.message.id, event.source.user_id, getattr(event.source, 'group_id', None), "", event.timestamp, event.reply_token, event.to_dict())

@handler.add(MessageEvent, message=FileMessageContent)
def handle_file(event):
    queue_message.send("message", "file", event.message.id, event.source.user_id, getattr(event.source, 'group_id', None), event.message.file_name if hasattr(event.message, 'file_name') else "", event.timestamp, event.reply_token, event.to_dict())

@handler.add(MessageEvent, message=StickerMessageContent)
def handle_sticker(event):
    queue_message.send("message", "sticker", event.message.id, event.source.user_id, getattr(event.source, 'group_id', None), f"sticker:{event.message.package_id}/{event.message.sticker_id}", event.timestamp, event.reply_token, event.to_dict())

@handler.add(JoinEvent)
def handle_join(event):
    queue_message.send("event", "join", str(event.timestamp), event.source.user_id if hasattr(event.source, 'user_id') else "system", getattr(event.source, 'group_id', None), "", event.timestamp, None, event.to_dict())

@handler.add(LeaveEvent)
def handle_leave(event):
    queue_message.send("event", "leave", str(event.timestamp), event.source.user_id if hasattr(event.source, 'user_id') else "system", getattr(event.source, 'group_id', None), "", event.timestamp, None, event.to_dict())

@handler.add(MemberJoinedEvent)
def handle_member_join(event):
    queue_message.send("event", "member_joined", str(event.timestamp), "system", event.source.group_id, "", event.timestamp, None, event.to_dict())

@handler.add(MemberLeftEvent)
def handle_member_leave(event):
    queue_message.send("event", "member_left", str(event.timestamp), "system", event.source.group_id, "", event.timestamp, None, event.to_dict())

@handler.add(UnsendEvent)
def handle_unsend(event):
    queue_message.send("event", "unsend", event.unsend.message_id, "system", getattr(event.source, 'group_id', None), "", event.timestamp, None, event.to_dict())

@handler.default()
def handle_default(event):
    logger.info(f"Unhandled event: {type(event).__name__}")

# ─── Webhook Endpoint ─────────────────────────────

@router.post("/webhook")
async def webhook(request: Request):
    """LINE webhook — verify signature, ACK, queue processing"""
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")
    
    try:
        handler.handle(body.decode(), signature)
    except InvalidSignatureError:
        return Response("Invalid signature", status_code=400)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        # Still return 200 so LINE doesn't retry
        return Response("OK")
    
    return Response("OK")
