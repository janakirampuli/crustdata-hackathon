"""Form server: the reviewer's survey list + approval page, and the per-token respondent form.

Run with `uv run forms` (FORMS_HOST / FORMS_PORT override 127.0.0.1:8000).
"""

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from pydantic import ValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from . import store
from .schema import OTHER, CampaignConfig, parse_answers
from .tools import base_url

HERE = Path(__file__).parent
STATUS = {"draft": ("Draft", ""), "changes_requested": ("Changes requested", "warn"),
          "approved": ("Approved", "ok"), "fielding": ("Fielding", "info"), "closed": ("Closed", "")}
PARTICIPANT = {"created": ("Not sent", ""), "invited": ("Invited", "info"), "opened": ("Opened", "warn"),
               "responded": ("Responded", "ok"), "opted_out": ("Opted out", "bad"), "expired": ("No response", "")}
# Workflow order: what we ask, who we target, who we invited, how fieldwork is going, what came back, what it means.
TABS = [("survey", "Survey"), ("participants", "Participants"), ("progress", "Progress"),
        ("responses", "Responses"), ("analytics", "Analytics"), ("activity", "Activity")]
TAB_ALIASES = {"audience": "participants"}  # Audience merged into Participants
QUALITY = {"high": ("High quality", "ok"), "ok": ("OK", "info"), "low": ("Low priority", "warn"),
           "spam": ("Likely spam", "bad")}
VERIFIED = {"pending": ("Pending", ""), "ok": ("Verified", "ok"), "flag": ("Flagged", "warn"), "fail": ("Failed", "bad")}


def rail_surveys() -> list[dict]:
    return [{"id": s["id"], "title": s["spec"].title, "status": s["status"], "tone": STATUS.get(s["status"], ("", ""))[1],
             "invites": s["invites"], "responses": s["responses"]} for s in store.list_surveys()]


_credits = {"at": 0.0, "value": None}


def crustdata_credits() -> float | None:
    """Zero-credit balance lookup, cached for 30s. None when Crustdata isn't configured or reachable."""
    if time.monotonic() - _credits["at"] > 30:
        try:
            from skills.crustdata.client import get_client

            data = get_client().get_credits()
            _credits["value"] = data.get("credits") if isinstance(data, dict) else None
        except Exception:
            _credits["value"] = None
        _credits["at"] = time.monotonic()
    return _credits["value"]


OPS = {"(.)": "contains", "=": "is", "!=": "is not", "in": "is one of", "not_in": "is not one of", "=>": "≥",
       ">": ">", "=<": "≤", "<": "<", "[.]": "matches", "(!)": "excludes", "is_null": "is empty",
       "is_not_null": "is set", "has_all": "has all of", "geo_distance": "within"}


def humanize(key: str) -> str:
    """currentJobTitles / company_headcount_latest -> 'current job titles' / 'company headcount latest'."""
    import re

    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(key)).replace("_", " ").replace(".", " › ").lower()


def mark_placeholders(text: str) -> Markup:
    return Markup(re.sub(r"\{([a-z_]+)\}", r'<span class="ph">{\1}</span>', str(escape(text))))


def mark_line(body: str, line: str | None) -> Markup:
    """The email body with its personal (or fallback) line highlighted."""
    body, line = str(escape(body)), str(escape(line or ""))
    return Markup(body.replace(line, f"<mark>{line}</mark>", 1) if line else body)


def make_templates(*extra_dirs: Path) -> Jinja2Templates:
    """Templates for console pages. Extra dirs come first, so other apps can add pages that extend console.html."""
    t = Jinja2Templates(directory=[*extra_dirs, HERE / "templates"],
                        context_processors=[lambda request: {"rail_surveys": rail_surveys()}])
    t.env.globals.update(QUALITY=QUALITY, OPS=OPS, OTHER=OTHER, STATUS=STATUS, VERIFIED=VERIFIED, PARTICIPANT=PARTICIPANT, TABS=TABS)
    t.env.filters.update(humanize=humanize, mark_placeholders=mark_placeholders, mark_line=mark_line)
    return t


app = FastAPI(title="Survey forms")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = make_templates()


def _render(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def _not_found(request: Request, message: str) -> HTMLResponse:
    return _render(request, "message.html", 404, title="Not found", message=message)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/surveys")


@app.get("/api/rail")
def rail():
    return {"surveys": rail_surveys(), "credits": crustdata_credits()}


@app.get("/api/search-index")
def search_index():
    """Everything the ⌘K palette can jump to on the form side: surveys and the people invited to them."""
    surveys = store.list_surveys()
    people = []
    for sv in surveys:
        for p in store.list_participants(sv["id"]):
            t = p["target"]
            people.append({"name": t.get("name"), "title": t.get("title"), "company": t.get("company"),
                           "state": p["state"], "survey_id": sv["id"], "survey": sv["spec"].title})
    return {"surveys": [{"id": sv["id"], "title": sv["spec"].title, "status": sv["status"],
                         "status_label": STATUS.get(sv["status"], (sv["status"], ""))[0],
                         "question": sv["spec"].research_question} for sv in surveys],
            "people": people, "tabs": TABS}


@app.get("/surveys", response_class=HTMLResponse)
def survey_list(request: Request):
    return _render(request, "list.html", surveys=store.list_surveys())


@app.get("/surveys/{survey_id}", response_class=HTMLResponse)
def workspace(request: Request, survey_id: str, tab: str | None = None, split: str = "seniority", error: str = ""):
    from skills.campaign import analytics, mailer, service

    row = store.get_survey(survey_id)
    if row is None:
        return _not_found(request, "No survey with that id.")
    tabs = dict(TABS)
    tab = TAB_ALIASES.get(tab, tab)
    if tab not in tabs:
        tab = "survey" if row["status"] in ("draft", "changes_requested") else "progress"
    ctx = {"row": row, "survey": row["spec"], "config": row["config"], "audience": row["audience"], "tab": tab,
           "progress": service.status(survey_id), "error": error, "base_url": base_url(), "email_mode": mailer.mode()}
    if tab == "progress":
        ctx["events"] = store.list_events(survey_id, limit=8)
        ctx["timeline"] = _timeline(store.list_responses(survey_id), row)
    elif tab == "participants":
        ctx["participants"] = store.list_participants(survey_id)
    elif tab == "responses":
        from skills.campaign import quality

        responses = store.list_responses(survey_id)
        ctx["responses"] = sorted(responses, key=lambda r: -(r["quality_score"] if r["quality_score"] is not None else -1))
        ctx["quality"] = quality.summary(survey_id)
    elif tab == "analytics":
        ctx["stats"] = analytics.compute(survey_id)
        ctx["split"] = split if split in analytics.SEGMENTS else "seniority"
        ctx["segments"] = analytics.SEGMENTS
        ctx["insights"] = store.get_insights(survey_id)
    elif tab == "activity":
        ctx["events"] = store.list_events(survey_id)
        ctx["outbox"] = store.list_outbox(survey_id)
    elif tab == "survey":
        ctx["responses"] = store.list_responses(survey_id)
    return _render(request, "workspace.html", **ctx)


def _timeline(responses: list[dict], row: dict) -> list[dict]:
    """Responses per time bucket since launch, for the progress sparkline."""
    from datetime import datetime, timezone

    if not row["launched_at"]:
        return []
    start = datetime.fromisoformat(row["launched_at"])
    end = datetime.fromisoformat(row["closed_at"] or datetime.now(timezone.utc).isoformat())
    span = max((end - start).total_seconds(), 60)
    buckets = 24
    counts = [0] * buckets
    for r in responses:
        i = int((datetime.fromisoformat(r["submitted_at"]) - start).total_seconds() / span * buckets)
        counts[min(max(i, 0), buckets - 1)] += 1
    total, out = 0, []
    for c in counts:
        total += c
        out.append({"count": c, "total": total})
    return out


@app.post("/surveys/{survey_id}/config")
async def save_config(request: Request, survey_id: str):
    row = store.get_survey(survey_id)
    if row is None:
        return _not_found(request, "No survey with that id.")
    form = await request.form()
    try:
        config = CampaignConfig.model_validate({k: int(form[k]) for k in CampaignConfig.model_fields if form.get(k)})
    except (ValueError, ValidationError) as e:
        msg = e.errors()[0]["msg"] if isinstance(e, ValidationError) else "Settings must be whole numbers."
        return RedirectResponse(f"/surveys/{survey_id}?tab=progress&error={quote(msg)}", status_code=303)
    store.set_config(survey_id, config)
    store.log_event(survey_id, "config", detail=config.model_dump())
    return RedirectResponse(f"/surveys/{survey_id}?tab=progress", status_code=303)


@app.post("/surveys/{survey_id}/participants")
def add_participant(request: Request, survey_id: str, name: str = Form(...), email: str = Form(...),
                    title: str = Form(""), company: str = Form("")):
    """Adds one person by hand (e.g. yourself for a demo) and sends their invite like any other target."""
    from skills.campaign import service

    email = email.strip()
    if "@" not in email:
        return RedirectResponse(f"/surveys/{survey_id}?tab=participants&error={quote('Enter a valid email address.')}",
                                status_code=303)
    target = {"crustdata_person_id": f"manual:{email.lower()}", "name": name.strip(), "business_email": email,
              "title": title.strip() or None, "company": company.strip() or None,
              "why_qualified": "you were added to this study by the research team"}
    result = service.launch(survey_id, [target])
    problem = result.get("error") or next(iter([p.get("error") or p.get("reason")
                                                for p in result.get("not_sent", []) + result.get("skipped", [])]), None)
    suffix = f"&error={quote(str(problem))}" if problem else ""
    return RedirectResponse(f"/surveys/{survey_id}?tab=participants{suffix}", status_code=303)


@app.post("/surveys/{survey_id}/quality")
def rescore_quality(request: Request, survey_id: str):
    """Rescore every response now, and queue a model review of any open text that hasn't had one."""
    from skills.campaign import quality

    if store.get_survey(survey_id) is None:
        return _not_found(request, "No survey with that id.")
    quality.rescore(survey_id)
    if os.environ.get("QUALITY_REVIEW", "on") != "off":
        for r in store.list_responses(survey_id):
            if not r["quality_llm"]:
                quality.review_in_background(survey_id, r["token"])
    return RedirectResponse(f"/surveys/{survey_id}?tab=responses", status_code=303)


@app.post("/surveys/{survey_id}/nudge")
def nudge(request: Request, survey_id: str):
    from skills.campaign import service

    service.send_followups(survey_id, force=True)
    return RedirectResponse(f"/surveys/{survey_id}?tab=activity", status_code=303)


@app.post("/surveys/{survey_id}/insights")
def make_insights(request: Request, survey_id: str):
    from skills.campaign import insights

    result = insights.generate(survey_id)
    suffix = f"&error={quote(result['detail'])}" if "error" in result else ""
    return RedirectResponse(f"/surveys/{survey_id}?tab=analytics{suffix}", status_code=303)


@app.post("/surveys/{survey_id}/approve")
def approve(request: Request, survey_id: str):
    row = store.get_survey(survey_id)
    if row is None:
        return _not_found(request, "No survey with that id.")
    if row["status"] in ("draft", "changes_requested"):
        store.set_status(survey_id, "approved")
    return RedirectResponse(f"/surveys/{survey_id}", status_code=303)


@app.post("/surveys/{survey_id}/request-changes")
def request_changes(request: Request, survey_id: str, feedback: str = Form("")):
    row = store.get_survey(survey_id)
    if row is None:
        return _not_found(request, "No survey with that id.")
    if row["status"] in ("draft", "approved") and not store.invite_stats(survey_id)["invited"]:
        store.set_status(survey_id, "changes_requested", feedback.strip() or None)
    return RedirectResponse(f"/surveys/{survey_id}", status_code=303)


@app.post("/surveys/{survey_id}/close")
def close(request: Request, survey_id: str):
    from skills.campaign import service

    if store.get_survey(survey_id) is None:
        return _not_found(request, "No survey with that id.")
    service.close(survey_id, "closed by reviewer")
    return RedirectResponse(f"/surveys/{survey_id}?tab=progress", status_code=303)


def _respondent_context(token: str) -> tuple[dict | None, dict | None, str | None]:
    """(invite, survey row, reason the form can't be shown)."""
    invite = store.get_invite(token)
    if invite is None:
        return None, None, "This survey link isn't valid. Please use the link from your invitation email."
    row = store.get_survey(invite["survey_id"])
    if row["status"] == "closed":
        return invite, row, "This survey has closed. Thank you for your interest."
    if row["status"] not in ("approved", "fielding"):
        return invite, row, "This survey isn't open yet."
    if invite["state"] == "opted_out":
        return invite, row, "You opted out of this survey, so this link no longer works."
    return invite, row, None


@app.get("/s/{token}", response_class=HTMLResponse)
def respond_form(request: Request, token: str):
    invite, row, reason = _respondent_context(token)
    if reason:
        return _render(request, "message.html", 404 if invite is None else 200, title="Survey", message=reason)
    if store.get_response(token):
        return _render(request, "message.html", title="Already answered",
                       message="We already have your answers for this survey. Thank you!")
    if store.mark_opened(token):
        store.log_event(invite["survey_id"], "opened", token)
    return _render(request, "respond.html", survey=row["spec"], target=invite["target"], token=token,
                   values={}, errors={})


@app.post("/s/{token}", response_class=HTMLResponse)
async def respond_submit(request: Request, token: str):
    invite, row, reason = _respondent_context(token)
    if reason:
        return _render(request, "message.html", 404 if invite is None else 200, title="Survey", message=reason)
    form = await request.form()
    raw = {key: [str(v) for v in form.getlist(key)] for key in form.keys()}
    answers, errors = parse_answers(row["spec"], raw)
    if errors:
        return _render(request, "respond.html", 422, survey=row["spec"], target=invite["target"], token=token,
                       values=raw, errors=errors)
    typing, duration = _typing_meta(raw), _seconds_since(invite.get("opened_at"))
    if not store.save_response(invite, answers, request.headers.get("user-agent"), duration, typing):
        return _render(request, "message.html", title="Already answered",
                       message="We already have your answers for this survey. Thank you!")
    from skills.campaign import quality, service

    store.log_event(invite["survey_id"], "responded", token)
    quality.rescore(invite["survey_id"])
    if os.environ.get("QUALITY_REVIEW", "on") != "off" and any(
            q.type == "text" and answers.get(q.id) for q in row["spec"].questions):
        quality.review_in_background(invite["survey_id"], token)
    service.after_response(invite["survey_id"])
    return _render(request, "message.html", title="Thank you",
                   message="Your answers are in. Thank you for taking the time.")


def _typing_meta(raw: dict) -> dict | None:
    """Behaviour counts the form script posts as __meta: active seconds, and keys / pastes per text field."""
    try:
        meta = json.loads((raw.get("__meta") or [""])[0] or "null")
    except ValueError:
        return None
    if not isinstance(meta, dict):
        return None
    fields = {str(k)[:40]: {key: int(v.get(key, 0)) for key in ("keys", "pastes", "pasted_chars", "focus_ms")}
              for k, v in (meta.get("fields") or {}).items() if isinstance(v, dict)}
    active = meta.get("active_s")
    return {"active_s": round(float(active), 1) if isinstance(active, (int, float)) else None, "fields": fields}


def _seconds_since(iso: str | None) -> float | None:
    from datetime import datetime, timezone

    if not iso:
        return None
    return round((datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds(), 1)


@app.get("/s/{token}/opt-out", response_class=HTMLResponse)
def opt_out_page(request: Request, token: str):
    invite = store.get_invite(token)
    if invite is None:
        return _render(request, "message.html", 404, title="Survey", message="This link isn't valid.")
    return _render(request, "optout.html", token=token, done=invite["state"] == "opted_out")


@app.post("/s/{token}/opt-out", response_class=HTMLResponse)
def opt_out(request: Request, token: str):
    invite = store.get_invite(token)
    if invite is None:
        return _render(request, "message.html", 404, title="Survey", message="This link isn't valid.")
    if store.opt_out(token):
        store.log_event(invite["survey_id"], "opted_out", token)
    return _render(request, "optout.html", token=token, done=True)


def main() -> None:
    import uvicorn
    from dotenv import load_dotenv

    load_dotenv()
    from skills.campaign import service

    service.start_scheduler()
    uvicorn.run(app, host=os.environ.get("FORMS_HOST", "127.0.0.1"), port=int(os.environ.get("FORMS_PORT", "8000")))


if __name__ == "__main__":
    main()
