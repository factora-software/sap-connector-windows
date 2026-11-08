"""Factora-Client: nur über die öffentliche HTTP-API, Bearer-Key, stabiler Idempotency-Key."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import requests

from sap_connector.errors import FactoraError

_NAMESPACE = uuid.UUID("5a1f0c52-7b0e-4c58-9d0e-2f1c7a6b9e31")


@dataclass(frozen=True)
class FactoraResult:
    """Ergebnis eines Aufrufs. ``already_booked``: die Rechnung gab es schon (HTTP 409)."""

    status: str
    invoice_id: int | None
    xml_base64: str | None
    pdf_base64: str | None
    replayed: bool = False
    validation: dict[str, Any] | None = None


def idempotency_key(tenant_scope: str, billing_document: str) -> str:
    """Stabile UUID aus Mandant und Belegnummer: derselbe Beleg ergibt immer denselben Schlüssel."""
    return str(uuid.uuid5(_NAMESPACE, f"{tenant_scope}:{billing_document}"))


class FactoraClient:
    """Sendet den Atomic-Request. Der Key kommt aus der Umgebung, nie aus dem Code."""

    def __init__(self, base_url: str, api_key: str, session: requests.Session | None = None) -> None:
        """Speichert Basis-URL, Key und Session (für Tests austauschbar)."""
        self._url = base_url.rstrip("/") + "/invoices/atomic/"
        self._session = session or requests.Session()
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def probe_key(self) -> None:
        """Prüft Key und Scope ohne Rechnung: ein leerer Aufruf wird bei gültigem Key mit 400/422 beantwortet.

        Nichts wird angelegt und nichts abgerechnet (400 ist kostenfrei); 401/403 heißt: Key unbrauchbar.
        """
        try:
            resp = self._session.post(self._url, json={}, headers=self._headers, timeout=60)
        except requests.RequestException as exc:
            raise FactoraError(f"Factora nicht erreichbar: {exc}") from exc
        if resp.status_code not in (400, 409, 422):
            raise FactoraError(_probe_message(resp.status_code), resp.status_code)

    def create_invoice(self, payload: dict[str, Any], key: str) -> FactoraResult:
        """Ruft ``POST /invoices/atomic/`` auf und wertet die Antwort aus."""
        headers = {**self._headers, "Idempotency-Key": key}
        try:
            resp = self._session.post(self._url, json=payload, headers=headers, timeout=120)
        except requests.RequestException as exc:
            raise FactoraError(f"Factora nicht erreichbar: {exc}") from exc
        body = _json(resp)
        if resp.status_code in (200, 201):
            return _success(body, resp.headers.get("Idempotent-Replayed") == "true")
        if resp.status_code == 409 and body.get("data"):
            return FactoraResult("already_booked", body["data"].get("id"), None, None)
        raise FactoraError(_describe(resp.status_code, body), resp.status_code)


def _probe_message(status: int) -> str:
    """Klartext zur Antwort der Key-Probe."""
    if status in (401, 403):
        return f"Factora lehnt den Key ab (HTTP {status}): ungültig, abgelaufen, ohne Scope invoices:write oder IP nicht freigegeben."
    return f"Unerwartete Antwort der Key-Probe (HTTP {status})."


def _json(resp: requests.Response) -> dict[str, Any]:
    """Antwort-JSON; kein JSON ergibt ein leeres Objekt."""
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _success(body: dict[str, Any], replayed: bool) -> FactoraResult:
    """Baut das Ergebnis aus ``data`` der Erfolgsantwort."""
    data = body.get("data") or {}
    return FactoraResult(data.get("status", ""), data.get("id"), data.get("xml_base64"),
                         data.get("pdf_base64"), replayed, data.get("validation"))


def _describe(status: int, body: dict[str, Any]) -> str:
    """Fehlertext aus HTTP-Status und ``errors[]`` der Antwort."""
    errors = body.get("errors") or []
    parts = [f"{e.get('field', '')}: {e.get('message', '')}".strip(": ") for e in errors]
    return f"Factora lehnt ab (HTTP {status}): " + ("; ".join(parts) or "keine Details")
