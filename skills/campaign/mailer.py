"""Invite and follow-up emails. Every email lands in the outbox table with its delivery status.

EMAIL_MODE=log (default) only records them. EMAIL_MODE=resend sends through Resend (RESEND_API_KEY, EMAIL_FROM,
optional EMAIL_REPLY_TO). Mock addresses (.invalid) and, when EMAIL_ALLOWLIST (comma-separated emails or @domains) is
set, everyone not on it are only recorded, exactly as in log mode, so a demo can mix mock participants with real ones.
"""

import html
import os
import re
import threading
import time

import httpx

from skills.form_builder import store
from skills.form_builder.schema import Survey
from skills.form_builder.tools import base_url

RESEND_URL = "https://api.resend.com/emails"
MIN_GAP_S = 0.6  # Resend's default limit is 2 requests per second

_send_lock = threading.Lock()
_last_send = 0.0


def mode() -> str:
    return "resend" if os.environ.get("EMAIL_MODE", "log").lower() == "resend" else "log"


def _first_name(target: dict) -> str:
    return (target.get("name") or "there").split(" ")[0]


def _why(target: dict) -> str:
    if target.get("why_qualified"):
        return target["why_qualified"].rstrip(".")
    role = " at ".join(x for x in (target.get("title"), target.get("company")) if x)
    return f"of your role as {role}" if role else "of your role"


def _subject(survey: Survey, target: dict) -> str:
    return f"{_first_name(target)}, a {survey.estimated_minutes}-minute survey: {survey.title}"


def invite(survey_id: str, survey: Survey, token: str, target: dict, email: dict | None = None) -> dict:
    """`email` is the invite built from the survey's approved template; without one, the built-in wording is used."""
    link, opt = f"{base_url()}/s/{token}", f"{base_url()}/s/{token}/opt-out"
    if email is not None:
        return _deliver(survey_id, token, "invite", target.get("business_email"), email["subject"], email["body"],
                        _html_from_text(email["body"]), opt)
    n = len(survey.questions)
    paragraphs = [
        f"Hi {_first_name(target)},",
        "Would you be open to sharing your view in a short research survey? If not, ignore this email or opt out "
        "below and we won't contact you again.",
        f"We're reaching out because {_why(target)}. {survey.intro}",
        f"It's {n} questions and takes about {survey.estimated_minutes} minutes:",
    ]
    footer = "This link is personal to you and works once. Answers are used for this research only, never for sales."
    return _deliver(survey_id, token, "invite", target.get("business_email"), _subject(survey, target),
                    _text(paragraphs, link, footer, opt), _html(paragraphs, link, "Take the survey", footer, opt), opt)


def followup(survey_id: str, survey: Survey, token: str, target: dict) -> dict:
    link, opt = f"{base_url()}/s/{token}", f"{base_url()}/s/{token}/opt-out"
    paragraphs = [
        f"Hi {_first_name(target)},",
        f"A quick nudge in case this got buried. Your view would really help, and it takes about "
        f"{survey.estimated_minutes} minutes:",
    ]
    footer = "No worries if not. This is the last reminder."
    return _deliver(survey_id, token, "followup", target.get("business_email"), "Re: " + _subject(survey, target),
                    _text(paragraphs, link, footer, opt), _html(paragraphs, link, "Take the survey", footer, opt), opt)


def _text(paragraphs: list[str], link: str, footer: str, opt: str) -> str:
    return "\n\n".join([*paragraphs[:-1], f"{paragraphs[-1]}\n{link}", footer, f"Opt out: {opt}"]) + "\n"


def _html(paragraphs: list[str], link: str, cta: str, footer: str, opt: str) -> str:
    p = "".join(f'<p style="margin:0 0 14px">{html.escape(x)}</p>' for x in paragraphs)
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.55;color:#151922;'
        'max-width:560px">' + p +
        f'<p style="margin:18px 0"><a href="{html.escape(link)}" style="background:#2947c7;color:#ffffff;'
        f'padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block">'
        f'{html.escape(cta)}</a></p>'
        f'<p style="margin:0 0 14px;color:#4b5261;font-size:13px">{html.escape(footer)}</p>'
        f'<p style="margin:0;color:#7b8291;font-size:12px"><a href="{html.escape(opt)}" style="color:#7b8291">'
        'Opt out</a> of this survey.</p></div>'
    )


def _html_from_text(text: str) -> str:
    """HTML twin of a finished plain-text email: paragraphs, line breaks and clickable links."""
    def para(block: str) -> str:
        escaped = html.escape(block)
        linked = re.sub(r"(https?://[^\s<]+)", r'<a href="\1" style="color:#2947c7">\1</a>', escaped)
        return f'<p style="margin:0 0 14px">{linked.replace(chr(10), "<br>")}</p>'
    body = "".join(para(b) for b in re.split(r"\n\s*\n", text.strip()) if b.strip())
    return ('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;line-height:1.55;'
            f'color:#151922;max-width:560px">{body}</div>')


def _allowed(to: str) -> bool:
    raw = os.environ.get("EMAIL_ALLOWLIST", "").strip()
    if not raw:
        return True
    to = to.lower()
    for entry in (e.strip().lower() for e in raw.split(",") if e.strip()):
        if to == entry or (entry.startswith("@") and to.endswith(entry)):
            return True
    return False


def _resend(to: str, subject: str, text: str, html_body: str, opt: str, key: str) -> str:
    global _last_send
    api_key, sender = os.environ.get("RESEND_API_KEY"), os.environ.get("EMAIL_FROM")
    if not api_key or not sender:
        raise RuntimeError("EMAIL_MODE=resend needs RESEND_API_KEY and EMAIL_FROM")
    payload = {
        "from": sender, "to": [to], "subject": subject, "text": text, "html": html_body,
        "headers": {"List-Unsubscribe": f"<{opt}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
    }
    if reply_to := os.environ.get("EMAIL_REPLY_TO"):
        payload["reply_to"] = reply_to
    with _send_lock:
        wait = MIN_GAP_S - (time.monotonic() - _last_send)
        if wait > 0:
            time.sleep(wait)
        response = httpx.post(RESEND_URL, json=payload, timeout=20, headers={
            "Authorization": f"Bearer {api_key}", "Idempotency-Key": key})
        _last_send = time.monotonic()
    if response.status_code >= 400:
        try:
            detail = response.json().get("message") or response.text
        except ValueError:
            detail = response.text
        raise RuntimeError(f"Resend {response.status_code}: {detail}")
    return response.json().get("id", "")


def _deliver(survey_id: str, token: str, kind: str, to: str | None, subject: str, text: str, html_body: str,
             opt: str) -> dict:
    status, provider_id, error = "logged", None, None
    if mode() == "resend":
        if not to:
            status, error = "failed", "no email address"
        elif to.lower().endswith(".invalid"):
            error = "recorded only: mock address"
        elif not _allowed(to):
            error = "recorded only: not on EMAIL_ALLOWLIST"
        else:
            try:
                provider_id = _resend(to, subject, text, html_body, opt,
                                      key=f"{token}-{kind}-{store.invite_contact_count(token)}")
                status = "sent"
            except Exception as e:  # recorded on the outbox row and shown in the workspace
                status, error = "failed", str(e)[:300]
    store.add_outbox(survey_id, token, kind, to, subject, text, status, provider_id, error)
    return {"kind": kind, "to": to, "status": status, "error": error}


def delivered(result: dict) -> bool:
    return result["status"] in ("logged", "sent")
