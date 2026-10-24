from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.web import history_events


def test_history_events_replays_text_tool_calls_and_parsed_results():
    messages = [
        HumanMessage("find CTOs"),
        AIMessage(content=[{"type": "text", "text": "Searching."}],
                  tool_calls=[{"id": "t1", "name": "crustdata_search_people", "args": {"limit": 5}}]),
        ToolMessage('{"total_count": 3}', tool_call_id="t1", name="crustdata_search_people"),
        ToolMessage("not json", tool_call_id="t2", name="x"),
        AIMessage("Found 3."),
    ]
    assert history_events(messages) == [
        {"type": "user", "text": "find CTOs"},
        {"type": "text", "text": "Searching."},
        {"type": "tool_call", "id": "t1", "name": "crustdata_search_people", "args": {"limit": 5}},
        {"type": "tool_result", "id": "t1", "name": "crustdata_search_people", "content": {"total_count": 3}},
        {"type": "tool_result", "id": "t2", "name": "x", "content": "not json"},
        {"type": "text", "text": "Found 3."},
    ]


def test_history_events_keeps_web_search_cards_between_text_blocks():
    message = AIMessage(content=[
        {"type": "text", "text": "Let me check the market."},
        {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "observability vendors"}},
        {"type": "web_search_tool_result", "tool_use_id": "s1",
         "content": [{"type": "web_search_result", "title": "Top tools", "url": "https://x.io", "encrypted_content": "e"}]},
        {"type": "server_tool_use", "id": "s2", "name": "web_search", "input": {}, "partial_json": '{"query": "more"}'},
        {"type": "web_search_tool_result", "tool_use_id": "s2",
         "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}},
        {"type": "text", "text": "Datadog leads."},
    ])
    assert history_events([message]) == [
        {"type": "text", "text": "Let me check the market."},
        {"type": "tool_call", "id": "s1", "name": "web_search", "args": {"query": "observability vendors"}},
        {"type": "tool_result", "id": "s1", "name": "web_search",
         "content": {"results": [{"title": "Top tools", "url": "https://x.io", "page_age": None}]}},
        {"type": "tool_call", "id": "s2", "name": "web_search", "args": {"query": "more"}},
        {"type": "tool_result", "id": "s2", "name": "web_search", "content": {"error": "max_uses_exceeded"}},
        {"type": "text", "text": "Datadog leads."},
    ]
