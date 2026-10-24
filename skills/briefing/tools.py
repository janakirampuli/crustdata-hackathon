"""Briefing tools. Web search is an Anthropic server tool: Claude runs the searches itself, so there's no Python
function; agent/graph.py picks the tool version the configured model supports."""

MAX_SEARCHES_PER_TURN = 5

TOOLS = [{"type": "web_search", "name": "web_search", "max_uses": MAX_SEARCHES_PER_TURN}]
