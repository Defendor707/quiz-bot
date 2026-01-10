#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Session management optimizatsiyasi - concurrent access va memory management
"""
import asyncio
import time
import logging
from typing import Dict, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)

# Session locks - concurrent access uchun
_session_locks: Dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()


async def get_session_lock(session_key: str) -> asyncio.Lock:
    """Session uchun lock olish (thread-safe)"""
    async with _locks_lock:
        if session_key not in _session_locks:
            _session_locks[session_key] = asyncio.Lock()
        return _session_locks[session_key]


async def cleanup_session_lock(session_key: str):
    """Session lock ni tozalash"""
    async with _locks_lock:
        _session_locks.pop(session_key, None)


def get_active_sessions_count(bot_data: dict) -> int:
    """Aktiv sessionlar sonini olish (optimizatsiya)"""
    sessions = bot_data.get('sessions', {})
    if not sessions:
        return 0
    return sum(1 for s in sessions.values() if s.get('is_active', False))


def cleanup_old_sessions(bot_data: dict, max_age_seconds: int = 3600, max_sessions: int = 1000):
    """Eski sessionlarni tozalash va memory optimizatsiyasi
    
    Args:
        max_age_seconds: Eng eski session yoshi (sekundlarda)
        max_sessions: Maksimal sessionlar soni (memory limit)
    """
    sessions = bot_data.get('sessions', {})
    if not sessions:
        return 0
    
    current_time = time.time()
    removed = 0
    PAUSE_MAX_AGE = 6 * 60 * 60  # 6 soat - pauza qilingan sessionlar uchun
    
    # Inactive va eski sessionlarni tozalash
    keys_to_remove = []
    for key, session in sessions.items():
        # Agar pauza qilingan va 6 soatdan o'tgan bo'lsa, tozalash
        if session.get('is_paused', False):
            paused_at = session.get('paused_at', 0)
            if paused_at > 0 and (current_time - paused_at) > PAUSE_MAX_AGE:
                keys_to_remove.append(key)
                logger.info(f"🧹 Pauza qilingan session 6 soatdan o'tgan, tozalanmoqda: {key}")
                continue
        
        # Inactive va eski sessionlarni tozalash
        if not session.get('is_active', False):
            started_at = session.get('started_at', 0)
            if current_time - started_at > max_age_seconds:
                keys_to_remove.append(key)
    
    # Memory limit - eng eski sessionlarni tozalash
    if len(sessions) > max_sessions:
        # Eng eski sessionlarni topish
        sorted_sessions = sorted(
            sessions.items(),
            key=lambda x: x[1].get('started_at', 0)
        )
        # Eng eski sessionlarni tozalash
        excess = len(sessions) - max_sessions
        for key, _ in sorted_sessions[:excess]:
            if key not in keys_to_remove:
                keys_to_remove.append(key)
    
    # Tozalash
    for key in keys_to_remove:
        sessions.pop(key, None)
        removed += 1
    
    if removed > 0:
        logger.info(f"🧹 {removed} ta eski session tozalandi (memory optimizatsiyasi)")
    
    return removed
