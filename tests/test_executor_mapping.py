from computer_use_mcp.executor import ActionExecutor
from computer_use_mcp.models import DisplayInfo
from computer_use_mcp.state_manager import StateManager


class DummyAdapter:
    def require_display(self, display_id: str):
        return type(
            "Descriptor",
            (),
            {"width_px": 1000, "height_px": 500, "scale_factor": 1.0},
        )()


def test_map_point_scales_from_state_image_to_target_display():
    executor = ActionExecutor(
        adapter=DummyAdapter(),
        state_manager=StateManager(),
        monitor=type("Monitor", (), {"interrupted": lambda self: False})(),
        config=type(
            "Config",
            (),
            {"blocked_hotkeys": frozenset(), "max_type_chars": 200, "max_actions_per_call": 5},
        )(),
    )
    state = type(
        "State",
        (),
        {
            "display_id": "primary",
            "display": DisplayInfo(
                id="primary",
                name="d",
                is_primary=True,
                width_px=2000,
                height_px=1000,
                logical_width=1000,
                logical_height=500,
                scale_factor=2.0,
                origin_x_px=0,
                origin_y_px=0,
                logical_origin_x=0,
                logical_origin_y=0,
            ),
        },
    )()
    assert executor._map_point(state, 1000, 500) == (500, 250)
