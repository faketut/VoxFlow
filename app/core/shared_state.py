"""
Shared session state for the application.

All access goes through :data:`session_manager` which protects concurrent
reads/writes with a global ``asyncio.Lock`` and a per-session ``asyncio.Lock``
so simultaneous calls cannot corrupt each other's state.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator


Session = dict[str, Any]


class SessionManager:
    """Thread/async-safe registry of per-call session dicts."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._global_lock = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = {}

    async def _get_lock(self, call_sid: str) -> asyncio.Lock:
        async with self._global_lock:
            lock = self._locks.get(call_sid)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[call_sid] = lock
            return lock

    async def create(self, call_sid: str, **fields: Any) -> Session:
        """Atomically create and return a new session."""
        async with self._global_lock:
            session: Session = dict(fields)
            self._sessions[call_sid] = session
            self._locks.setdefault(call_sid, asyncio.Lock())
            return session

    async def get(self, call_sid: str) -> Session | None:
        async with self._global_lock:
            return self._sessions.get(call_sid)

    async def update(self, call_sid: str, **fields: Any) -> None:
        lock = await self._get_lock(call_sid)
        async with lock:
            session = self._sessions.get(call_sid)
            if session is not None:
                session.update(fields)

    async def pop(self, call_sid: str) -> Session | None:
        async with self._global_lock:
            self._locks.pop(call_sid, None)
            return self._sessions.pop(call_sid, None)

    async def find_by_uv_ws(self, uv_ws: Any) -> tuple[str | None, Session | None]:
        """Return (call_sid, session) whose ``uv_ws`` matches, or (None, None)."""
        async with self._global_lock:
            for sid, sess in self._sessions.items():
                if sess.get('uv_ws') is uv_ws:
                    return sid, sess
            return None, None

    @asynccontextmanager
    async def lock(self, call_sid: str) -> AsyncIterator[Session | None]:
        """Hold the per-session lock while mutating the session in a block."""
        per_lock = await self._get_lock(call_sid)
        async with per_lock:
            async with self._global_lock:
                session = self._sessions.get(call_sid)
            yield session


# Single process-wide instance.
session_manager = SessionManager()
