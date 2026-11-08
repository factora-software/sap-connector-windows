"""Gemeinsame Fixtures: Beleg im OData-Format, Mandantenkonfiguration, Factora-Attrappe."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from sap_connector.config import TenantConfig, load_config
from sap_connector.odata import unwrap

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cfg() -> TenantConfig:
    """Mandantenkonfiguration aus den Test-Fixtures."""
    return load_config(FIXTURES / "tenant.json")


@pytest.fixture
def doc() -> dict[str, Any]:
    """Frische Kopie des Beispielbelegs (veränderbar)."""
    raw = json.loads((FIXTURES / "billing_document.json").read_text(encoding="utf-8"))
    return copy.deepcopy(unwrap(raw))


class FakeResponse:
    """Minimale Antwort-Attrappe."""

    def __init__(self, status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        """Speichert Status, Body und Header."""
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self) -> dict[str, Any]:
        """Liefert den Body."""
        return self._body


class FakeSession:
    """Ersetzt ``requests.Session``: zeichnet Aufrufe auf, antwortet aus einer Liste."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        """Legt die vorbereiteten Antworten ab."""
        self.responses, self.calls = list(responses), []

    def post(self, url: str, json: dict[str, Any], headers: dict[str, str], timeout: int) -> FakeResponse:
        """Zeichnet den Aufruf auf und liefert die nächste Antwort."""
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)
