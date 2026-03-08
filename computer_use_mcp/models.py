from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Point(BaseModel):
    x: int
    y: int


class DisplayInfo(BaseModel):
    id: str
    name: str
    is_primary: bool
    width_px: int
    height_px: int
    logical_width: float
    logical_height: float
    scale_factor: float
    origin_x_px: int
    origin_y_px: int
    logical_origin_x: float
    logical_origin_y: float
    coordinate_space: Literal["screenshot_pixels"] = "screenshot_pixels"


class CursorInfo(BaseModel):
    x: int
    y: int
    visible: bool = True


class StateSummary(BaseModel):
    state_id: str
    display: DisplayInfo
    cursor: CursorInfo | None = None
    active_app: str | None = None
    active_window_title: str | None = None
    warnings: list[str] = Field(default_factory=list)


class DisplayListResult(BaseModel):
    platform: str
    displays: list[DisplayInfo]
    warnings: list[str] = Field(default_factory=list)


class ComputerStateResult(StateSummary):
    pass


class MoveAction(BaseModel):
    type: Literal["move"] = "move"
    x: int
    y: int
    duration_ms: int = 120


class ClickAction(BaseModel):
    type: Literal["click"] = "click"
    x: int
    y: int
    button: Literal["left", "middle", "right"] = "left"


class DoubleClickAction(BaseModel):
    type: Literal["double_click"] = "double_click"
    x: int
    y: int


class RightClickAction(BaseModel):
    type: Literal["right_click"] = "right_click"
    x: int
    y: int


class DragAction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["drag"] = "drag"
    from_point: Point = Field(alias="from")
    to: Point
    duration_ms: int = 250


class ScrollAction(BaseModel):
    type: Literal["scroll"] = "scroll"
    x: int
    y: int
    delta_x: int = 0
    delta_y: int = 0


class TypeAction(BaseModel):
    type: Literal["type"] = "type"
    text: str


class KeypressAction(BaseModel):
    type: Literal["keypress"] = "keypress"
    keys: list[str]


class WaitAction(BaseModel):
    type: Literal["wait"] = "wait"
    ms: int


ComputerAction = Annotated[
    MoveAction
    | ClickAction
    | DoubleClickAction
    | RightClickAction
    | DragAction
    | ScrollAction
    | TypeAction
    | KeypressAction
    | WaitAction,
    Field(discriminator="type"),
]


class ComputerActOptions(BaseModel):
    capture_after: bool = True
    pause_between_ms: int = 80
    post_action_wait_ms: int = 0
    reject_if_stale: bool = True


class ComputerActArgs(BaseModel):
    state_id: str
    display_id: str = "primary"
    actions: list[ComputerAction]
    options: ComputerActOptions = Field(default_factory=ComputerActOptions)


class AppliedActionResult(BaseModel):
    index: int
    type: str
    status: Literal["ok", "partial", "skipped", "error"]
    message: str | None = None


class InterventionInfo(BaseModel):
    event_type: Literal["keyboard", "mouse_click", "mouse_move", "scroll"]
    key: str | None = None
    x: int | None = None
    y: int | None = None
    timestamp: str


class ComputerActResult(BaseModel):
    status: Literal["ok", "interrupted", "rejected", "error"]
    execution_id: str
    applied: list[AppliedActionResult] = Field(default_factory=list)
    reason: str | None = None
    error_message: str | None = None
    interrupted_at_action_index: int | None = None
    intervention: InterventionInfo | None = None
    post_state: StateSummary | None = None
    warnings: list[str] = Field(default_factory=list)
