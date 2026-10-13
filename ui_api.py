"""HTTP client for the FastAPI backend, shared by the chat page (ui.py) and
the Graph Creator page (pages/graph_creator.py)."""
from __future__ import annotations

import httpx


class ApiError(Exception):
    pass


class ApiClient:
    """Small wrapper around the FastAPI backend."""

    def __init__(self, base_url: str, api_key: str, user_id: str):
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id
        self.headers = {"X-API-Key": api_key}

    def _request(self, method: str, path: str, **kwargs):
        try:
            # Agents can take a while (several model and BigQuery calls).
            response = httpx.request(
                method, self.base_url + path, headers=self.headers, timeout=180, **kwargs
            )
        except httpx.HTTPError as e:
            raise ApiError(f"Can't reach the API at {self.base_url}. Is it running? ({e})") from e
        if response.status_code == 401:
            raise ApiError("The API rejected the key. Check the API key in Settings.")
        if response.status_code >= 400:
            raise ApiError(f"API error {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else None

    def health(self) -> bool:
        try:
            return httpx.get(self.base_url + "/health", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def chat(self, message: str, session_id: str | None) -> dict:
        body = {"user_id": self.user_id, "message": message, "session_id": session_id}
        return self._request("POST", "/chat", json=body)

    def list_sessions(self) -> list[dict]:
        return self._request("GET", f"/sessions/{self.user_id}")

    def history(self, session_id: str) -> list[dict]:
        return self._request("GET", f"/sessions/{self.user_id}/{session_id}")

    def delete(self, session_id: str) -> None:
        self._request("DELETE", f"/sessions/{self.user_id}/{session_id}")

    # ---- Graph Creator ----
    def datasets(self, project: str | None) -> list[dict]:
        return self._request("GET", "/graphs/datasets", params={"project": project} if project else None)

    def graphs(self, project: str | None, dataset: str | None = None) -> dict:
        params = {k: v for k, v in {"project": project, "dataset": dataset}.items() if v}
        return self._request("GET", "/graphs", params=params)

    def propose_graph(self, project: str | None, dataset: str, name: str) -> dict:
        return self._request("POST", "/graphs/proposals", json={"project": project or None, "dataset": dataset, "name": name})

    def update_graph(self, proposal_id: str, spec: dict) -> dict:
        return self._request("PUT", f"/graphs/proposals/{proposal_id}", json={"spec": spec})

    def delete_graph(self, proposal_id: str) -> None:
        self._request("DELETE", f"/graphs/proposals/{proposal_id}")
