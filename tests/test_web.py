from fastapi.testclient import TestClient
import json

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from agent import web

from agent.web import app, history_events
from skills.form_builder import tools
from tests.test_form_builder import SURVEY


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


def test_streamed_turn_still_completes_web_search_cards_the_stream_skipped(monkeypatch):
    final = AIMessage(id="m1", content=[
        {"type": "text", "text": "Checking."},
        {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "pricing"}},
        {"type": "web_search_tool_result", "tool_use_id": "s1", "content": [{"title": "A", "url": "https://a.io"}]},
    ])

    class Agent:
        def stream(self, *args, **kwargs):
            meta = {"langgraph_node": "agent"}
            yield "messages", (AIMessageChunk(id="m1", content=[{"type": "text", "text": "Checking.", "index": 0}]), meta)
            yield "messages", (AIMessageChunk(id="m1", content=[
                {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {}, "index": 1}]), meta)
            yield "messages", (AIMessageChunk(id="m1", content=[
                {"type": "input_json_delta", "partial_json": '{"query": "pricing"}', "index": 1}]), meta)
            yield "updates", {"agent": {"messages": [final]}}

    monkeypatch.setattr(web, "get_agent", lambda: Agent())
    events = [json.loads(e[len("data: "):]) for e in web._turn_events("t", "hi")]
    assert [(e["type"], e.get("id")) for e in events] == [
        ("text", None), ("tool_call", "s1"), ("tool_result", "s1"), ("done", None)]


def test_survey_canvas_follows_the_approval_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("FORMS_DB", str(tmp_path / "forms.db"))
    client = TestClient(app)
    survey_id = tools.create_survey.invoke({"survey": SURVEY})["survey_id"]

    draft = client.get(f"/api/surveys/{survey_id}/canvas")
    assert draft.status_code == 200
    assert "Agent data infra" in draft.text and 'data-canvas="approve"' in draft.text

    client.post(f"/surveys/{survey_id}/request-changes", data={"feedback": "Drop the spend question"})
    changes = client.get(f"/api/surveys/{survey_id}/canvas").text
    assert "Drop the spend question" in changes and 'data-canvas="approve"' not in changes

    tools.revise_survey.invoke({"survey_id": survey_id, "survey": SURVEY})
    client.post(f"/surveys/{survey_id}/approve")
    approved = client.get(f"/api/surveys/{survey_id}/canvas").text
    assert "Approved" in approved and 'data-canvas="approve"' not in approved

    assert client.get("/api/surveys/nope/canvas").status_code == 404
