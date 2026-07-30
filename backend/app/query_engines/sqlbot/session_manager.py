from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Callable, Protocol

from app.query_engines.sqlbot.contracts import SQLBotSession, SQLBotSessionKey


class SessionFactory(Protocol):
    def __call__(self) -> tuple[str, str]:
        """Return external_chat_id and access_token."""


class SQLBotSessionManager:
    """Secret-bearing runtime cache; durable mappings are added by the router layer."""

    def __init__(
        self,
        max_age_seconds: int = 3600,
        on_bind: Callable[[SQLBotSession], None] | None = None,
    ):
        self.max_age = timedelta(seconds=max_age_seconds)
        self.on_bind = on_bind
        self._sessions: dict[tuple[str, ...], SQLBotSession] = {}
        self._lock = RLock()

    def get_or_create(
        self,
        key: SQLBotSessionKey,
        factory: SessionFactory,
        *,
        force_rebuild: bool = False,
    ) -> SQLBotSession:
        now = datetime.now(UTC)
        cache_key = key.as_tuple()
        with self._lock:
            current = self._sessions.get(cache_key)
            expired = current is not None and now - current.created_at > self.max_age
            if current is not None and not force_rebuild and not expired:
                current.last_used_at = now
                return current
            external_chat_id, access_token = factory()
            session = SQLBotSession(
                key=key,
                external_chat_id=str(external_chat_id),
                access_token=access_token,
                generation=(current.generation + 1) if current else 1,
            )
            self._sessions[cache_key] = session
            if self.on_bind:
                self.on_bind(session)
            return session

    def invalidate(self, key: SQLBotSessionKey) -> None:
        with self._lock:
            self._sessions.pop(key.as_tuple(), None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
