"""Campaign mechanics: launch, follow-ups, auto-close and progress. Plain code; the agent calls it through tools,
the workspace UI through the form server, and a background thread runs `tick` every 30s."""

import os
import threading
import time
from datetime import datetime, timedelta, timezone

from skills.form_builder import personalize, store
from skills.form_builder.schema import Audience
from skills.form_builder.tools import base_url

from . import mailer

LAUNCHABLE = ("approved", "fielding")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def launch(survey_id: str, targets: list[dict], audience: Audience | None = None) -> dict:
    """Invites targets up to the survey's max_invites. Targets without a business email are skipped."""
    row = store.get_survey(survey_id)
    if row is None:
        return {"error": "not_found", "survey_id": survey_id}
    if row["status"] not in LAUNCHABLE:
        return {"error": "not_approved" if row["status"] != "closed" else "closed", "status": row["status"]}
    config = row["config"]
    if audience is not None:
        if not audience.brief and row["brief"]:
            audience = audience.model_copy(update={"brief": row["brief"]})
        store.set_audience(survey_id, audience)

    existing = {p["crustdata_person_id"] for p in store.list_participants(survey_id)}
    room = config.max_invites - len(existing)
    skipped, fresh = [], []
    for t in targets:
        pid = str(t.get("crustdata_person_id"))
        if pid in existing:
            skipped.append({"crustdata_person_id": pid, "name": t.get("name"), "reason": "already invited"})
        elif not t.get("business_email"):
            skipped.append({"crustdata_person_id": pid, "name": t.get("name"), "reason": "no business email"})
        elif len(fresh) >= room:
            skipped.append({"crustdata_person_id": pid, "name": t.get("name"), "reason": f"max_invites ({config.max_invites}) reached"})
        else:
            fresh.append(t)
            existing.add(pid)

    if fresh and row["status"] != "fielding":
        store.mark_launched(survey_id, config.deadline_minutes)
        store.log_event(survey_id, "launched", detail={"max_invites": config.max_invites,
                                                       "target_responses": config.target_responses})
    invites, spec = store.create_invites(survey_id, fresh), row["spec"]
    emails = (personalize.build_emails(spec, fresh, [f"{base_url()}/s/{inv['token']}" for inv in invites])
              if spec.email and fresh else [None] * len(fresh))
    invited, not_sent = [], []
    for t, inv, email in zip(fresh, invites, emails):
        result = mailer.invite(survey_id, spec, inv["token"], t, email)
        personal = {"personalized": email["personalized"]} if email else {}
        person = {"crustdata_person_id": inv["crustdata_person_id"], "name": t.get("name"),
                  "email": t.get("business_email"), "token": inv["token"], "email_status": result["status"], **personal}
        if mailer.delivered(result):
            store.mark_contacted(inv["token"], t.get("business_email"), followup=False)
            store.log_event(survey_id, "invited", inv["token"], {"email": t.get("business_email"),
                                                                 "status": result["status"], **personal})
            invited.append(person)
        else:
            store.log_event(survey_id, "send_failed", inv["token"], {"email": t.get("business_email"),
                                                                     "status": result["status"], "error": result["error"]})
            not_sent.append({**person, "error": result["error"]})
    return {"survey_id": survey_id, "invited": invited, "not_sent": not_sent, "skipped": skipped,
            "email_mode": mailer.mode(), "emails": _email_summary(emails), **status(survey_id)}


def _email_summary(emails: list[dict | None]) -> dict | str:
    built = [e for e in emails if e]
    if len(built) < len(emails):
        return "no email template on this survey: built-in invite wording"
    return {"personalized": sum(e["personalized"] for e in built),
            "fallback": sum(not e["personalized"] for e in built),
            "sample": next((e for e in built if e["personalized"]), built[0] if built else None)}


def send_followups(survey_id: str, force: bool = False) -> list[dict]:
    """Nudges people who haven't answered. `force` ignores the follow-up delay (a manual nudge)."""
    row = store.get_survey(survey_id)
    if row is None or row["status"] != "fielding":
        return []
    config, sent = row["config"], []
    due_before = _now() - timedelta(minutes=config.followup_after_minutes)
    for p in store.list_participants(survey_id):
        if p["state"] not in ("invited", "opened") or p["followups_sent"] >= config.max_followups:
            continue
        if not force and datetime.fromisoformat(p["last_contacted_at"]) > due_before:
            continue
        result = mailer.followup(survey_id, row["spec"], p["token"], {**p["target"], "business_email": p["email"]})
        # Counted even when delivery fails, so the scheduler doesn't retry the same reminder every tick.
        store.mark_contacted(p["token"], p["email"], followup=True)
        if mailer.delivered(result):
            store.log_event(survey_id, "followup", p["token"], {"n": p["followups_sent"] + 1})
            sent.append({"name": p["target"].get("name"), "email": p["email"]})
        else:
            store.log_event(survey_id, "send_failed", p["token"], {"email": p["email"], "status": result["status"],
                                                                   "error": result["error"]})
    return sent


_writing: set[str] = set()


def writing_findings(survey_id: str) -> bool:
    return survey_id in _writing


def write_findings(survey_id: str) -> None:
    """Writes the findings report in the background; the model call takes about a minute."""
    if os.environ.get("FINDINGS_ON_CLOSE", "on") == "off" or survey_id in _writing:
        return

    def run():
        from . import insights

        try:
            insights.generate(survey_id)
        except Exception as e:
            print(f"[campaign] findings failed for {survey_id}: {type(e).__name__}: {e}")
        finally:
            _writing.discard(survey_id)

    _writing.add(survey_id)
    threading.Thread(target=run, name=f"findings-{survey_id}", daemon=True).start()


def close(survey_id: str, reason: str, report: bool = True) -> bool:
    if store.close_survey(survey_id, reason):
        store.log_event(survey_id, "closed", detail={"reason": reason})
        if report:
            write_findings(survey_id)
        return True
    return False


def after_response(survey_id: str, report: bool = True) -> None:
    row = store.get_survey(survey_id)
    if row and row["status"] == "fielding" and store.invite_stats(survey_id)["responded"] >= row["config"].target_responses:
        close(survey_id, "target reached", report)


def status(survey_id: str) -> dict:
    row = store.get_survey(survey_id)
    st = store.invite_stats(survey_id)
    config = row["config"]
    from . import quality

    out = {"status": row["status"], "stats": st, "quality": quality.summary(survey_id)["tiers"], "target_responses": config.target_responses,
           "max_invites": config.max_invites, "invites_left": max(config.max_invites - st["invited"], 0),
           "launched_at": row["launched_at"], "closes_at": row["closes_at"], "closed_at": row["closed_at"],
           "close_reason": row["close_reason"]}
    if row["status"] == "fielding" and row["launched_at"] and row["closes_at"]:
        start, end = datetime.fromisoformat(row["launched_at"]), datetime.fromisoformat(row["closes_at"])
        elapsed = min(max((_now() - start) / (end - start), 0), 1) if end > start else 1
        progress = st["responded"] / config.target_responses
        out["time_elapsed_pct"] = round(elapsed * 100)
        out["target_pct"] = round(progress * 100)
        out["minutes_left"] = max(int((end - _now()).total_seconds() // 60), 0)
        if progress >= elapsed or elapsed < 0.2:
            out["recommendation"] = "on track"
        elif out["invites_left"] > 0:
            out["recommendation"] = f"behind pace: invite more people ({out['invites_left']} invites left)"
        else:
            out["recommendation"] = "behind pace and out of invites: raise max_invites or widen the audience"
    return out


def tick() -> None:
    for row in store.surveys_in_field():
        if row["closes_at"] and _now() >= datetime.fromisoformat(row["closes_at"]):
            close(row["id"], "deadline")
            continue
        after_response(row["id"])
        send_followups(row["id"])


_started = False


def start_scheduler(interval: float = 30.0) -> None:
    global _started
    if _started:
        return
    _started = True

    def loop():
        while True:
            try:
                tick()
            except Exception as e:  # keep the loop alive; the next tick retries
                print(f"[campaign] tick failed: {type(e).__name__}: {e}")
            time.sleep(interval)

    threading.Thread(target=loop, name="campaign-scheduler", daemon=True).start()
