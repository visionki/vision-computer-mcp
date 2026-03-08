from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import json


@dataclass(slots=True)
class DebugRecorder:
    enabled: bool
    base_dir: Path
    save_images: bool = True
    events_path: Path | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if self.enabled:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            (self.base_dir / "images").mkdir(parents=True, exist_ok=True)
            self.events_path = self.base_dir / "events.jsonl"
        else:
            self.events_path = None

    def record(self, event: str, payload: dict, image_bytes: bytes | None = None) -> None:
        if not self.enabled:
            return
        timestamp = datetime.now(UTC)
        image_path = None
        if image_bytes is not None and self.save_images:
            image_name = f"{timestamp.strftime('%Y%m%d_%H%M%S_%f')}_{event.replace('.', '_')}.png"
            image_path = self.base_dir / "images" / image_name
            image_path.write_bytes(image_bytes)
        entry = {
            "timestamp": timestamp.isoformat(),
            "event": event,
            "payload": payload,
        }
        if image_path is not None:
            entry["image_path"] = str(image_path)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
