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

    def identify_company(self, body: dict) -> Any:
        return self._request("POST", "company/identify", body)

    def search_companies(self, body: dict) -> dict:
        return self._request("POST", "company/search", body)

    def search_jobs(self, body: dict) -> dict:
        return self._request("POST", "job/search", body)

    def get_credits(self) -> Any:
        return self._request("GET", "user/credits")


_client: CrustdataClient | None = None


def get_client() -> CrustdataClient:
    global _client
    if _client is None:
        _client = CrustdataClient()
    return _client
