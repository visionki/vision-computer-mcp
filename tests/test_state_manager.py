from computer_use_mcp.models import DisplayInfo
from computer_use_mcp.state_manager import StateManager


def make_display(display_id: str = "primary") -> DisplayInfo:
    return DisplayInfo(
        id=display_id,
        name="Test Display",
        is_primary=True,
        width_px=1440,
        height_px=900,
        logical_width=1440,
        logical_height=900,
        scale_factor=1.0,
        origin_x_px=0,
        origin_y_px=0,
        logical_origin_x=0,
        logical_origin_y=0,
    )


def test_state_manager_tracks_latest_state_per_display():
    manager = StateManager(ttl_seconds=120)
    first = manager.issue_state(
        display=make_display(),
        cursor=None,
        active_app=None,
        active_window_title=None,
        screenshot_png=b"first",
    )
    second = manager.issue_state(
        display=make_display(),
        cursor=None,
        active_app=None,
        active_window_title=None,
        screenshot_png=b"second",
    )
    assert manager.is_latest(second.state_id, "primary") is True
    assert manager.is_latest(first.state_id, "primary") is False


def test_state_summary_contains_display_metadata():
    manager = StateManager(ttl_seconds=120)
    record = manager.issue_state(
        display=make_display(),
        cursor=None,
        active_app="Browser",
        active_window_title="Example",
        screenshot_png=b"data",
    )
    summary = record.summary()
    assert summary.display.id == "primary"
    assert summary.active_window_title == "Example"
