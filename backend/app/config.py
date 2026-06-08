"""LGIAP Configuration"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR.parent / '.env')  # .env lives at /data/lgiap/.env, not under backend/

# PostgreSQL
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:lgiap123@127.0.0.1:5432/lgiap")

# Redis
REDIS_URL = os.environ.get("REDIS_URL", "redis://:langfuse2026@127.0.0.1:6379/0")

# LINE
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_TOKEN = os.environ.get("LINE_CHANNEL_TOKEN", "")

# Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Embeddings
EMBEDDING_API_URL = os.environ.get("EMBEDDING_API_URL", "http://127.0.0.1:11434/api/embed")
EMBEDDING_MODEL = "bge-m3"

# 2nd Brain
BRAIN_CORPUS_PATH = Path("/data/emba-second-brain/corpus.json")
BRAIN_BUILD_GRAPH = Path("/data/emba-second-brain/build_graph.py")

# AI Filter
AI_FILTER_ENABLED = os.environ.get("AI_FILTER_ENABLED", "true").lower() == "true"
AI_FILTER_MIN_RATING = int(os.environ.get("AI_FILTER_MIN_RATING", "2"))
