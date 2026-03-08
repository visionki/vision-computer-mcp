from computer_use_mcp.models import ComputerActArgs, DragAction, KeypressAction


def test_drag_action_alias_parses_from_field():
    request = ComputerActArgs.model_validate(
        {
            "state_id": "state_1",
            "display_id": "primary",
            "actions": [
                {
                    "type": "drag",
                    "from": {"x": 1, "y": 2},
                    "to": {"x": 9, "y": 10},
                    "duration_ms": 200,
                }
            ],
        }
    )
    action = request.actions[0]
    assert isinstance(action, DragAction)
    assert action.from_point.x == 1
    assert action.to.y == 10


def test_keypress_action_parses_keys():
    request = ComputerActArgs.model_validate(
        {
            "state_id": "state_1",
            "actions": [{"type": "keypress", "keys": ["cmd", "l"]}],
        }
    )
    action = request.actions[0]
    assert isinstance(action, KeypressAction)
    assert action.keys == ["cmd", "l"]
