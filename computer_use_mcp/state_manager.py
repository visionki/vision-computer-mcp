from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import uuid4

from computer_use_mcp.models import CursorInfo, DisplayInfo, StateSummary


@dataclass(slots=True)
class StateRecord:
    state_id: str
    created_at: datetime
    display_id: str
    display: DisplayInfo
    cursor: CursorInfo | None
    active_app: str | None
    active_window_title: str | None
    screenshot_png: bytes
    warnings: list[str]

    def summary(self) -> StateSummary:
        return StateSummary(
            state_id=self.state_id,
            display=self.display,
            cursor=self.cursor,
            active_app=self.active_app,
            active_window_title=self.active_window_title,
            warnings=list(self.warnings),
        )


class StateManager:
    def __init__(self, ttl_seconds: int = 120, max_records: int = 64):
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_records = max_records
        self._records: dict[str, StateRecord] = {}
        self._ordered_ids: deque[str] = deque()
        self._latest_by_display: dict[str, str] = {}
        self._lock = RLock()

    def issue_state(
        self,
        *,
        display: DisplayInfo,
        cursor: CursorInfo | None,
        active_app: str | None,
        active_window_title: str | None,
        screenshot_png: bytes,
        warnings: list[str] | None = None,
    ) -> StateRecord:
        with self._lock:
            self._prune_locked()
            state_id = self._new_id("state")
            record = StateRecord(
                state_id=state_id,
                created_at=datetime.now(UTC),
                display_id=display.id,
                display=display,
                cursor=cursor,
                active_app=active_app,
                active_window_title=active_window_title,
                screenshot_png=screenshot_png,
                warnings=list(warnings or []),
            )
            self._records[state_id] = record
            self._ordered_ids.append(state_id)
            self._latest_by_display[display.id] = state_id
            while len(self._ordered_ids) > self._max_records:
                oldest = self._ordered_ids.popleft()
                self._records.pop(oldest, None)
            return record

    def get(self, state_id: str) -> StateRecord | None:
        with self._lock:
            self._prune_locked()
            return self._records.get(state_id)

    def is_latest(self, state_id: str, display_id: str) -> bool:
        with self._lock:
            self._prune_locked()
            return self._latest_by_display.get(display_id) == state_id

    def latest(self, display_id: str) -> StateRecord | None:
        with self._lock:
            self._prune_locked()
            state_id = self._latest_by_display.get(display_id)
            return self._records.get(state_id) if state_id else None

    def new_execution_id(self) -> str:
        return self._new_id("exec")

    def _prune_locked(self) -> None:
        cutoff = datetime.now(UTC) - self._ttl
        stale_ids = [state_id for state_id, record in self._records.items() if record.created_at < cutoff]
        for state_id in stale_ids:
            self._records.pop(state_id, None)
            try:
                self._ordered_ids.remove(state_id)
            except ValueError:
                pass
        for display_id, state_id in list(self._latest_by_display.items()):
            if state_id not in self._records:
                self._latest_by_display.pop(display_id, None)

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
