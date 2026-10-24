"""Form server: the reviewer's survey list + approval page, and the per-token respondent form.

Run with `uv run forms` (FORMS_HOST / FORMS_PORT override 127.0.0.1:8000).
"""

import os
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import store
from .schema import OTHER, parse_answers
from .tools import base_url

HERE = Path(__file__).parent
STATUS = {"draft": ("Draft", ""), "changes_requested": ("Changes requested", "warn"),
          "approved": ("Approved", "ok"), "closed": ("Closed", "")}
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


def make_templates(*extra_dirs: Path) -> Jinja2Templates:
    """Templates for console pages. Extra dirs come first, so other apps can add pages that extend console.html."""
    t = Jinja2Templates(directory=[*extra_dirs, HERE / "templates"],
                        context_processors=[lambda request: {"rail_surveys": rail_surveys()}])
    t.env.globals.update(OTHER=OTHER, STATUS=STATUS, VERIFIED=VERIFIED)
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


@app.get("/surveys", response_class=HTMLResponse)
def survey_list(request: Request):
    return _render(request, "list.html", surveys=store.list_surveys())


@app.get("/surveys/{survey_id}", response_class=HTMLResponse)
def review(request: Request, survey_id: str):
    row = store.get_survey(survey_id)
    if row is None:
        return _not_found(request, "No survey with that id.")
    return _render(request, "review.html", row=row, survey=row["spec"], stats=store.invite_stats(survey_id),
                   responses=store.list_responses(survey_id), base_url=base_url())


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
    if store.get_survey(survey_id) is None:
        return _not_found(request, "No survey with that id.")
    store.set_status(survey_id, "closed")
    return RedirectResponse(f"/surveys/{survey_id}", status_code=303)


def _respondent_context(token: str) -> tuple[dict | None, dict | None, str | None]:
    """(invite, survey row, reason the form can't be shown)."""
    invite = store.get_invite(token)
    if invite is None:
        return None, None, "This survey link isn't valid. Please use the link from your invitation email."
    row = store.get_survey(invite["survey_id"])
    if row["status"] == "closed":
        return invite, row, "This survey has closed. Thank you for your interest."
    if row["status"] != "approved":
        return invite, row, "This survey isn't open yet."
    return invite, row, None


@app.get("/s/{token}", response_class=HTMLResponse)
def respond_form(request: Request, token: str):
    invite, row, reason = _respondent_context(token)
    if reason:
        return _render(request, "message.html", 404 if invite is None else 200, title="Survey", message=reason)
    if store.get_response(token):
        return _render(request, "message.html", title="Already answered",
                       message="We already have your answers for this survey. Thank you!")
    store.mark_opened(token)
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
    if not store.save_response(invite, answers, request.headers.get("user-agent")):
        return _render(request, "message.html", title="Already answered",
                       message="We already have your answers for this survey. Thank you!")
    return _render(request, "message.html", title="Thank you",
                   message="Your answers are in. Thank you for taking the time.")


def main() -> None:
    import uvicorn
    from dotenv import load_dotenv

    load_dotenv()
    uvicorn.run(app, host=os.environ.get("FORMS_HOST", "127.0.0.1"), port=int(os.environ.get("FORMS_PORT", "8000")))


if __name__ == "__main__":
    main()
