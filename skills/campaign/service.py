"""Campaign mechanics: launch, follow-ups, auto-close and progress. Plain code; the agent calls it through tools,
the workspace UI through the form server, and a background thread runs `tick` every 30s."""

import threading
import time
from datetime import datetime, timedelta, timezone

from skills.form_builder import store
from skills.form_builder.schema import Audience

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
    invited = []
    for t, inv in zip(fresh, store.create_invites(survey_id, fresh)):
        mailer.invite(survey_id, row["spec"], inv["token"], t)
        store.mark_contacted(inv["token"], t.get("business_email"), followup=False)
        store.log_event(survey_id, "invited", inv["token"], {"email": t.get("business_email")})
        invited.append({"crustdata_person_id": inv["crustdata_person_id"], "name": t.get("name"),
                        "email": t.get("business_email"), "token": inv["token"]})
    return {"survey_id": survey_id, "invited": invited, "skipped": skipped, "email_mode": mailer.mode(),
            **status(survey_id)}


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
        mailer.followup(survey_id, row["spec"], p["token"], {**p["target"], "business_email": p["email"]})
        store.mark_contacted(p["token"], p["email"], followup=True)
        store.log_event(survey_id, "followup", p["token"], {"n": p["followups_sent"] + 1})
        sent.append({"name": p["target"].get("name"), "email": p["email"]})
    return sent


def close(survey_id: str, reason: str) -> bool:
    if store.close_survey(survey_id, reason):
        store.log_event(survey_id, "closed", detail={"reason": reason})
        return True
    return False


def after_response(survey_id: str) -> None:
    row = store.get_survey(survey_id)
    if row and row["status"] == "fielding" and store.invite_stats(survey_id)["responded"] >= row["config"].target_responses:
        close(survey_id, "target reached")


def status(survey_id: str) -> dict:
    row = store.get_survey(survey_id)
    st = store.invite_stats(survey_id)
    config = row["config"]
    out = {"status": row["status"], "stats": st, "target_responses": config.target_responses,
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
