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
