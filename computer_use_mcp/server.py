from __future__ import annotations

from argparse import ArgumentParser
from base64 import b64encode
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
import json
import logging

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent

from computer_use_mcp.platform import create_adapter
from computer_use_mcp.config import ServerConfig
from computer_use_mcp.debug import DebugRecorder
from computer_use_mcp.executor import ActionExecutor
from computer_use_mcp.models import (
    ComputerActArgs,
    ComputerActResult,
    ComputerStateResult,
    DisplayListResult,
)
from computer_use_mcp.monitor import HumanOverrideMonitor
from computer_use_mcp.state_manager import StateManager


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppContext:
    config: ServerConfig
    adapter: object
    state_manager: StateManager
    monitor: HumanOverrideMonitor
    executor: ActionExecutor
    debug_recorder: DebugRecorder
    startup_warnings: list[str]


def _result_with_content(
    structured_model,
    *,
    png_bytes: bytes | None = None,
    text_summary: str | None = None,
    is_error: bool = False,
) -> CallToolResult:
    content: list = []
    if text_summary:
        content.append(TextContent(type="text", text=text_summary))
    else:
        content.append(
            TextContent(
                type="text",
                text=json.dumps(structured_model.model_dump(mode="json"), ensure_ascii=False, indent=2),
            )
        )
    if png_bytes is not None:
        content.append(
            ImageContent(
                type="image",
                mimeType="image/png",
                data=b64encode(png_bytes).decode("ascii"),
            )
        )
    return CallToolResult(
        content=content,
        structuredContent=structured_model.model_dump(mode="json"),
        isError=is_error,
    )


@asynccontextmanager
async def app_lifespan(_server: FastMCP):
    config = ServerConfig.from_env()
    monitor = HumanOverrideMonitor(
        threshold_px=config.mouse_interrupt_threshold_px,
        enabled=config.human_override_enabled,
    )
    monitor.start()
    adapter = create_adapter(monitor.filter)
    startup_warnings = []
    if monitor.startup_warning:
        startup_warnings.append(monitor.startup_warning)
    startup_warnings.extend(adapter.startup_warnings())
    state_manager = StateManager(ttl_seconds=config.state_ttl_seconds)
    debug_recorder = DebugRecorder(
        enabled=config.debug_enabled,
        base_dir=Path(config.debug_dir),
        save_images=config.debug_save_images,
    )
    executor = ActionExecutor(
        adapter,
        state_manager,
        monitor,
        config,
        startup_warnings,
        debug_recorder=debug_recorder,
    )
    yield AppContext(
        config=config,
        adapter=adapter,
        state_manager=state_manager,
        monitor=monitor,
        executor=executor,
        debug_recorder=debug_recorder,
        startup_warnings=startup_warnings,
    )
    monitor.stop()


mcp = FastMCP(
    name="Vision Computer MCP",
    instructions=(
        "This server exposes a computer-use loop over MCP. First call computer_get_state to get the latest "
        "screenshot and state_id. Then call computer_act with the same state_id and a required non-empty "
        "actions array. All coordinates are screenshot pixel coordinates from the latest image."
    ),
    lifespan=app_lifespan,
)


@mcp.tool(
    description=(
        "List available displays. Call this when you need screen dimensions or multiple monitors. "
        "Use the returned display_id in later computer_get_state and computer_act calls."
    )
)
async def computer_list_displays(ctx: Context) -> CallToolResult:
    app: AppContext = ctx.request_context.lifespan_context
    displays = app.adapter.list_displays()
    result = DisplayListResult(
        platform=app.adapter.platform_name,
        displays=displays,
        warnings=list(app.startup_warnings),
    )
    app.debug_recorder.record(
        "computer_list_displays.result",
        result.model_dump(mode="json"),
    )
    return _result_with_content(
        result,
        text_summary=f"{len(displays)} display(s) available on {app.adapter.platform_name}.",
    )


@mcp.tool(
    description=(
        "Capture the current desktop state for a display and return a screenshot image. Always call this before "
        "computer_act. Save the returned state_id and use screenshot pixel coordinates from this exact image."
    )
)
async def computer_get_state(
    display_id: str = "primary",
    include_cursor: bool = True,
    ctx: Context | None = None,
) -> CallToolResult:
    assert ctx is not None
    app: AppContext = ctx.request_context.lifespan_context
    capture = app.adapter.capture_display(
        display_id,
        include_cursor=include_cursor and app.config.include_cursor_by_default,
    )
    record = app.state_manager.issue_state(
        display=capture.display,
        cursor=capture.cursor,
        active_app=capture.active_app,
        active_window_title=capture.active_window_title,
        screenshot_png=capture.png_bytes,
        warnings=list(app.startup_warnings),
    )
    result = ComputerStateResult(**record.summary().model_dump(mode="json"))
    app.debug_recorder.record(
        "computer_get_state.result",
        result.model_dump(mode="json"),
        image_bytes=record.screenshot_png,
    )
    return _result_with_content(
        result,
        png_bytes=record.screenshot_png,
        text_summary=(
            f"Captured state {record.state_id} for display {display_id}. "
            "Coordinates use screenshot pixel space."
        ),
    )


@mcp.tool(
    description=(
        "Execute a short batch of computer actions for the latest screenshot state. Required params: state_id and "
        "actions. actions must be a non-empty array. Example: {state_id:'...', actions:[{type:'click', x:520, "
        "y:410, button:'left'}]}. Supported action types: move, click, double_click, right_click, drag, scroll, "
        "type, keypress, wait. Use post_action_wait_ms to wait after the action batch before the automatic post-state screenshot. "
        "Set max action batching as needed; the server does not enforce a small fixed limit by default."
    )
)
async def computer_act(
    state_id: str,
    actions: list[dict],
    display_id: str = "primary",
    capture_after: bool = True,
    pause_between_ms: int = 80,
    reject_if_stale: bool = True,
    post_action_wait_ms: int = 0,
    ctx: Context | None = None,
) -> CallToolResult:
    assert ctx is not None
    app: AppContext = ctx.request_context.lifespan_context
    request = ComputerActArgs.model_validate(
        {
            "state_id": state_id,
            "display_id": display_id,
            "actions": actions,
            "options": {
                "capture_after": capture_after,
                "pause_between_ms": pause_between_ms,
                "reject_if_stale": reject_if_stale,
                "post_action_wait_ms": post_action_wait_ms,
            },
        }
    )
    envelope = app.executor.execute(request)
    result = ComputerActResult(**envelope.result.model_dump(mode="json"))
    return _result_with_content(
        result,
        png_bytes=envelope.png_bytes,
        text_summary=f"computer_act finished with status={result.status}.",
        is_error=result.status == "error",
    )


@mcp.tool(
    description=(
        "Debug tool: capture the current desktop screenshot and return only image content, without text summary or structured metadata. "
        "Use this to test whether the client/host can preserve MCP image tool results into model context."
    )
)
async def debug_get_state_image_only(
    display_id: str = "primary",
    include_cursor: bool = True,
    ctx: Context | None = None,
) -> CallToolResult:
    assert ctx is not None
    app: AppContext = ctx.request_context.lifespan_context
    capture = app.adapter.capture_display(
        display_id,
        include_cursor=include_cursor and app.config.include_cursor_by_default,
    )
    record = app.state_manager.issue_state(
        display=capture.display,
        cursor=capture.cursor,
        active_app=capture.active_app,
        active_window_title=capture.active_window_title,
        screenshot_png=capture.png_bytes,
        warnings=list(app.startup_warnings),
    )
    app.debug_recorder.record(
        "debug_get_state_image_only.result",
        record.summary().model_dump(mode="json"),
        image_bytes=record.screenshot_png,
    )
    return CallToolResult(
        content=[
            ImageContent(
                type="image",
                mimeType="image/png",
                data=b64encode(record.screenshot_png).decode("ascii"),
            )
        ],
        structuredContent={
            "state_id": record.state_id,
            "display_id": record.display_id,
            "image_only": True,
        },
        isError=False,
    )


def main() -> None:
    parser = ArgumentParser(description="Vision Computer MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport to run the MCP server with.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--path", default="/mcp")
    args = parser.parse_args()
    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        if hasattr(mcp.settings, "path"):
            mcp.settings.path = args.path
    mcp.run(transport=args.transport)
