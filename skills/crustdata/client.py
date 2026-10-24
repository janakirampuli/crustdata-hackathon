"""Thin Crustdata HTTP client. One method per endpoint; no retries beyond what httpx gives us."""

import os
from typing import Any

import httpx

BASE_URL = "https://api.crustdata.com/"
API_VERSION = "2025-11-01"


class CrustdataError(Exception):
    def __init__(self, status: int, body: Any):
        super().__init__(f"Crustdata HTTP {status}: {body}")
        self.status = status
        self.body = body


class CrustdataClient:
    def __init__(self, api_key: str | None = None, timeout: float = 60.0):
        key = api_key or os.environ.get("CRUSTDATA_API_KEY")
        if not key:
            raise RuntimeError("CRUSTDATA_API_KEY is not set")
        self._http = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {key}",
                "x-api-version": API_VERSION,
                "Content-Type": "application/json",
            },
        )

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        response = self._http.request(method, path, json=body)
        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise CrustdataError(response.status_code, detail)
        return response.json()

    def search_people(self, body: dict) -> dict:
        return self._request("POST", "person/search", body)

    def enrich_person(self, body: dict) -> Any:
        return self._request("POST", "person/enrich", body)

    def enrich_contact(self, body: dict) -> Any:
        if os.environ.get("CRUSTDATA_MOCK_CONTACT_ENRICH", "").lower() in {"1", "true", "yes"}:
            return mock_contact_enrich(body)
        # /person/contact/enrich is still disabled on our key (403), but /person/enrich serves the same
        # contact.business_emails in the same response shape. It has no verified mode.
        return self.enrich_person({k: v for k, v in body.items() if k != "verified"})

    def identify_company(self, body: dict) -> Any:
        return self._request("POST", "company/identify", body)

    def search_companies(self, body: dict) -> dict:
        return self._request("POST", "company/search", body)

    def search_jobs(self, body: dict) -> dict:
        return self._request("POST", "job/search", body)

    def get_credits(self) -> Any:
        return self._request("GET", "user/credits")


def mock_contact_enrich(body: dict) -> list[dict]:
    """Documented /person/contact/enrich response shape, until the endpoint is enabled on our key.

    Addresses must never reach a real stranger, so they go to plus-addresses of our own inbox
    (MOCK_EMAIL_INBOX=team@gmail.com -> team+<linkedin-slug>@gmail.com) or to the reserved .invalid TLD.
    """
    inbox = os.environ.get("MOCK_EMAIL_INBOX", "").strip()
    results = []
    for url in body.get("professional_network_profile_urls") or []:
        slug = "".join(c for c in url.rstrip("/").rsplit("/", 1)[-1].lower() if c.isalnum()) or "unknown"
        if "@" in inbox:
            local, domain = inbox.split("@", 1)
            email = f"{local}+{slug}@{domain}"
        else:
            email = f"{slug}@mock.invalid"
        results.append({
            "matched_on": url,
            "match_type": "professional_network_profile_url",
            "match_status": "matched",
            "matches": [{
                "confidence_score": 1.0,
                "person_data": {"contact": {"business_emails": [{"email": email, "status": "deliverable"}]}},
            }],
        })
    return results


_client: CrustdataClient | None = None


def get_client() -> CrustdataClient:
    global _client
    if _client is None:
        _client = CrustdataClient()
    return _client
