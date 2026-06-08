#!/usr/bin/env python3
"""Sync all missing LINE user profiles"""
import sys
sys.path.insert(0, "backend")
from app.profile_sync import sync_profiles

count = sync_profiles()
print(f"Synced {count} profiles")
