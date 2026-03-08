from __future__ import annotations

from dataclasses import dataclass
import time

from computer_use_mcp.platform_base import DesktopAdapter
from computer_use_mcp.config import ServerConfig
from computer_use_mcp.debug import DebugRecorder
from computer_use_mcp.keys import normalize_key_combo
from computer_use_mcp.models import (
    AppliedActionResult,
    ClickAction,
    ComputerActArgs,
    ComputerActResult,
    DoubleClickAction,
    DragAction,
    KeypressAction,
    MoveAction,
    RightClickAction,
    ScrollAction,
    TypeAction,
    WaitAction,
)
from computer_use_mcp.monitor import HumanOverrideMonitor
from computer_use_mcp.state_manager import StateManager, StateRecord


@dataclass(slots=True)
class ExecutionEnvelope:
    result: ComputerActResult
    png_bytes: bytes | None


class ActionExecutor:
    def __init__(
        self,
        adapter: DesktopAdapter,
        state_manager: StateManager,
        monitor: HumanOverrideMonitor,
        config: ServerConfig,
        startup_warnings: list[str] | None = None,
        debug_recorder: DebugRecorder | None = None,
    ) -> None:
        self.adapter = adapter
        self.state_manager = state_manager
        self.monitor = monitor
        self.config = config
        self.startup_warnings = list(startup_warnings or [])
        self.debug_recorder = debug_recorder

    def execute(self, request: ComputerActArgs) -> ExecutionEnvelope:
        execution_id = self.state_manager.new_execution_id()
        state = self.state_manager.get(request.state_id)
        target_descriptor = None
        try:
            target_descriptor = self.adapter.require_display(request.display_id)
        except Exception:
            target_descriptor = None
        self._debug(
            "computer_act.request",
            {
                "execution_id": execution_id,
                "request": request.model_dump(mode="json", by_alias=True),
                "state_found": state is not None,
                "state_display": state.display.model_dump(mode="json") if state else None,
                "target_display": target_descriptor.to_public().model_dump(mode="json")
                if target_descriptor
                else None,
            },
        )
        if state is None:
            return self._finish(
                ExecutionEnvelope(
                    result=ComputerActResult(
                        status="rejected",
                        execution_id=execution_id,
                        reason="unknown_state",
                        error_message=f"Unknown state_id: {request.state_id}",
                        warnings=list(self.startup_warnings),
                    ),
                    png_bytes=None,
                )
            )
        if state.display_id != request.display_id:
            return self._finish(
                ExecutionEnvelope(
                    result=ComputerActResult(
                        status="rejected",
                        execution_id=execution_id,
                        reason="display_mismatch",
                        error_message=(
                            f"state_id {request.state_id} belongs to display {state.display_id}, "
                            f"but request used {request.display_id}."
                        ),
                        warnings=list(self.startup_warnings),
                    ),
                    png_bytes=None,
                )
            )
        if request.options.reject_if_stale and not self.state_manager.is_latest(
            request.state_id, request.display_id
        ):
            return self._finish(
                ExecutionEnvelope(
                    result=ComputerActResult(
                        status="rejected",
                        execution_id=execution_id,
                        reason="stale_state",
                        error_message="state_id is no longer the latest state for this display.",
                        warnings=list(self.startup_warnings),
                    ),
                    png_bytes=None,
                )
            )
        if self.config.max_actions_per_call > 0 and len(request.actions) > self.config.max_actions_per_call:
            return self._finish(
                ExecutionEnvelope(
                    result=ComputerActResult(
                        status="rejected",
                        execution_id=execution_id,
                        reason="too_many_actions",
                        error_message=(
                            f"A single call may contain at most {self.config.max_actions_per_call} actions."
                        ),
                        warnings=list(self.startup_warnings),
                    ),
                    png_bytes=None,
                )
            )

        applied: list[AppliedActionResult] = []
        current_index = 0
        action_type = ""
        self.monitor.arm()
        try:
            for current_index, action in enumerate(request.actions):
                action_type = action.type
                self._check_human_override()
                self._validate_action(state, action)
                mapping = self._mapping_debug_for_action(state, action)
                self._debug(
                    "computer_act.action",
                    {
                        "execution_id": execution_id,
                        "index": current_index,
                        "action": action.model_dump(mode="json", by_alias=True),
                        "mapping": mapping,
                    },
                )
                self._run_action(state, action)
                applied.append(
                    AppliedActionResult(
                        index=current_index,
                        type=action.type,
                        status="ok",
                        message=(
                            f"mapped={mapping}" if mapping else None
                        ),
                    )
                )
                if current_index < len(request.actions) - 1 and request.options.pause_between_ms > 0:
                    self._sleep_with_override_check(request.options.pause_between_ms)
        except HumanOverrideInterrupted:
            intervention = self.monitor.consume_signal()
            if action_type and current_index < len(request.actions):
                applied.append(
                    AppliedActionResult(
                        index=current_index,
                        type=action_type or request.actions[current_index].type,
                        status="partial",
                        message="Interrupted by local user input.",
                    )
                )
            post_state = self._capture_post_state(request.display_id)
            return self._finish(
                ExecutionEnvelope(
                    result=ComputerActResult(
                        status="interrupted",
                        execution_id=execution_id,
                        reason="human_override",
                        interrupted_at_action_index=current_index,
                        applied=applied,
                        intervention=intervention,
                        post_state=post_state.summary(),
                        warnings=list(dict.fromkeys(self.startup_warnings + post_state.warnings)),
                    ),
                    png_bytes=post_state.screenshot_png,
                )
            )
        except Exception as exc:
            post_state = self._capture_post_state(request.display_id, tolerate_errors=True)
            return self._finish(
                ExecutionEnvelope(
                    result=ComputerActResult(
                        status="error",
                        execution_id=execution_id,
                        applied=applied,
                        reason=type(exc).__name__,
                        error_message=str(exc),
                        post_state=post_state.summary() if post_state else None,
                        warnings=list(
                            dict.fromkeys(
                                self.startup_warnings + (post_state.warnings if post_state else [])
                            )
                        ),
                    ),
                    png_bytes=post_state.screenshot_png if post_state else None,
                )
            )
        finally:
            self.monitor.disarm()

        if request.options.capture_after:
            if request.options.post_action_wait_ms > 0:
                self._sleep_with_override_check(request.options.post_action_wait_ms)
            post_state = self._capture_post_state(request.display_id)
            return self._finish(
                ExecutionEnvelope(
                    result=ComputerActResult(
                        status="ok",
                        execution_id=execution_id,
                        applied=applied,
                        post_state=post_state.summary(),
                        warnings=list(dict.fromkeys(self.startup_warnings + post_state.warnings)),
                    ),
                    png_bytes=post_state.screenshot_png,
                )
            )

        return self._finish(
            ExecutionEnvelope(
                result=ComputerActResult(
                    status="ok",
                    execution_id=execution_id,
                    applied=applied,
                    warnings=list(self.startup_warnings),
                ),
                png_bytes=None,
            )
        )

    def _validate_action(self, state: StateRecord, action) -> None:
        if isinstance(action, (MoveAction, ClickAction, DoubleClickAction, RightClickAction, ScrollAction)):
            self._validate_state_point(state, action.x, action.y)
            return
        if isinstance(action, DragAction):
            self._validate_state_point(state, action.from_point.x, action.from_point.y)
            self._validate_state_point(state, action.to.x, action.to.y)
            return
        if isinstance(action, TypeAction):
            if len(action.text) > self.config.max_type_chars:
                raise ValueError(
                    f"type action text length exceeds limit {self.config.max_type_chars}."
                )
            return
        if isinstance(action, KeypressAction):
            combo = normalize_key_combo(action.keys)
            if combo in self.config.blocked_hotkeys:
                raise ValueError(f"Blocked hotkey combo: {combo}")
            return
        if isinstance(action, WaitAction):
            if action.ms < 0:
                raise ValueError("wait.ms must be non-negative")
            return
        raise ValueError(f"Unsupported action type: {action.type}")

    def _validate_state_point(self, state: StateRecord, x: int, y: int) -> None:
        if not (0 <= x < state.display.width_px and 0 <= y < state.display.height_px):
            raise ValueError(
                f"Point ({x}, {y}) is outside screenshot bounds {state.display.width_px}x{state.display.height_px}."
            )

    def _map_point(self, state: StateRecord, x: int, y: int) -> tuple[int, int]:
        descriptor = self.adapter.require_display(state.display_id)
        mapped_x = int(round(x * descriptor.width_px / max(state.display.width_px, 1)))
        mapped_y = int(round(y * descriptor.height_px / max(state.display.height_px, 1)))
        mapped_x = max(0, min(descriptor.width_px - 1, mapped_x))
        mapped_y = max(0, min(descriptor.height_px - 1, mapped_y))
        return mapped_x, mapped_y

    def _mapping_debug_for_action(self, state: StateRecord, action) -> dict | None:
        descriptor = self.adapter.require_display(state.display_id)
        payload = {
            "state_display_px": [state.display.width_px, state.display.height_px],
            "target_display_px": [descriptor.width_px, descriptor.height_px],
            "target_scale_factor": descriptor.scale_factor,
            "capture_scale_factor": state.display.scale_factor,
        }
        if isinstance(action, (MoveAction, ClickAction, DoubleClickAction, RightClickAction, ScrollAction)):
            mapped = self._map_point(state, action.x, action.y)
            payload.update({"from": [action.x, action.y], "to": list(mapped)})
            return payload
        if isinstance(action, DragAction):
            mapped_from = self._map_point(state, action.from_point.x, action.from_point.y)
            mapped_to = self._map_point(state, action.to.x, action.to.y)
            payload.update(
                {
                    "from": [action.from_point.x, action.from_point.y],
                    "to": [action.to.x, action.to.y],
                    "mapped_from": list(mapped_from),
                    "mapped_to": list(mapped_to),
                }
            )
            return payload
        return None

    def _run_action(self, state: StateRecord, action) -> None:
        display_id = state.display_id
        if isinstance(action, MoveAction):
            x, y = self._map_point(state, action.x, action.y)
            self.adapter.move_mouse(display_id, x, y, action.duration_ms)
            return
        if isinstance(action, ClickAction):
            x, y = self._map_point(state, action.x, action.y)
            self.adapter.click_mouse(display_id, x, y, action.button, count=1)
            return
        if isinstance(action, DoubleClickAction):
            x, y = self._map_point(state, action.x, action.y)
            self.adapter.click_mouse(display_id, x, y, "left", count=2)
            return
        if isinstance(action, RightClickAction):
            x, y = self._map_point(state, action.x, action.y)
            self.adapter.click_mouse(display_id, x, y, "right", count=1)
            return
        if isinstance(action, DragAction):
            from_x, from_y = self._map_point(state, action.from_point.x, action.from_point.y)
            to_x, to_y = self._map_point(state, action.to.x, action.to.y)
            self.adapter.drag_mouse(display_id, from_x, from_y, to_x, to_y, action.duration_ms)
            return
        if isinstance(action, ScrollAction):
            x, y = self._map_point(state, action.x, action.y)
            self.adapter.scroll_at(display_id, x, y, action.delta_x, action.delta_y)
            return
        if isinstance(action, TypeAction):
            self._type_with_override(action.text)
            return
        if isinstance(action, KeypressAction):
            self.adapter.press_keys(action.keys)
            return
        if isinstance(action, WaitAction):
            self._sleep_with_override_check(action.ms)
            return
        raise ValueError(f"Unsupported action type: {action.type}")

    def _type_with_override(self, text: str) -> None:
        for character in text:
            self._check_human_override()
            self.adapter.type_text(character)
            self._sleep_with_override_check(10)

    def _sleep_with_override_check(self, ms: int) -> None:
        if ms <= 0:
            return
        remaining = ms / 1000
        while remaining > 0:
            self._check_human_override()
            slice_seconds = min(remaining, 0.03)
            time.sleep(slice_seconds)
            remaining -= slice_seconds

    def _check_human_override(self) -> None:
        if self.monitor.interrupted():
            raise HumanOverrideInterrupted

    def _capture_post_state(
        self,
        display_id: str,
        *,
        tolerate_errors: bool = False,
    ) -> StateRecord | None:
        try:
            capture = self.adapter.capture_display(display_id, include_cursor=True)
            warnings = list(dict.fromkeys(self.startup_warnings))
            record = self.state_manager.issue_state(
                display=capture.display,
                cursor=capture.cursor,
                active_app=capture.active_app,
                active_window_title=capture.active_window_title,
                screenshot_png=capture.png_bytes,
                warnings=warnings,
            )
            self._debug(
                "computer_state.captured",
                {
                    "state_id": record.state_id,
                    "display_id": display_id,
                    "display": record.display.model_dump(mode="json"),
                    "cursor": record.cursor.model_dump(mode="json") if record.cursor else None,
                    "active_app": record.active_app,
                    "active_window_title": record.active_window_title,
                },
                image_bytes=record.screenshot_png,
            )
            return record
        except Exception as exc:
            self._debug(
                "computer_state.capture_error",
                {"display_id": display_id, "error": str(exc), "type": type(exc).__name__},
            )
            if tolerate_errors:
                return None
            raise

    def _debug(self, event: str, payload: dict, image_bytes: bytes | None = None) -> None:
        if self.debug_recorder is not None:
            self.debug_recorder.record(event, payload, image_bytes=image_bytes)

    def _finish(self, envelope: ExecutionEnvelope) -> ExecutionEnvelope:
        self._debug(
            "computer_act.result",
            envelope.result.model_dump(mode="json"),
            image_bytes=envelope.png_bytes,
        )
        return envelope


class HumanOverrideInterrupted(Exception):
    pass
