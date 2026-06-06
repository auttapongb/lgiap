"""LGIAP — Dramatiq Task Workers"""
import dramatiq
from dramatiq.brokers.redis import RedisBroker
from app.config import REDIS_URL

redis_broker = RedisBroker(url=REDIS_URL)
dramatiq.set_broker(redis_broker)
