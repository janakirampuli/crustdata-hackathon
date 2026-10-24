from agent.graph import _server_tool


def test_web_search_version_follows_model():
    spec = {"type": "web_search", "name": "web_search", "max_uses": 5}
    assert _server_tool(spec, "claude-haiku-5-5") == {**spec, "type": "web_search_20250305"}
    assert _server_tool(spec, "claude-sonnet-5-5") == {**spec, "type": "web_search_20260209"}
