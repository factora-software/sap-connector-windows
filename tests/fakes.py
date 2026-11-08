"""Attrappen für SAP und Factora (Dauerbetrieb): ohne Netz, mit festem Verhalten."""

from __future__ import annotations

import base64
import copy
from collections.abc import Callable
from typing import Any

from sap_connector.errors import FactoraError
from sap_connector.factora_client import FactoraResult


class FakeSap:
    """Liefert eine feste Belegliste und je Nummer eine Kopie des Beispielbelegs."""

    def __init__(self, numbers: list[str], template: dict[str, Any]) -> None:
        """Merkt Nummern und Vorlage."""
        self.numbers, self.template, self.fetched = sorted(numbers), template, []

    def list_since(self, after: str, types: list[str], top: int) -> list[str]:
        """Nummern größer als ``after``, höchstens ``top``."""
        return [n for n in self.numbers if n > after][:top]

    def fetch(self, number: str) -> dict[str, Any]:
        """Beleg mit der gewünschten Nummer."""
        self.fetched.append(number)
        doc = copy.deepcopy(self.template)
        doc["BillingDocument"] = number
        return doc


class FakeFactora:
    """Antwortet je Beleg über eine Funktion; zeichnet Aufrufe auf."""

    def __init__(self, behaviour: Callable[[str], FactoraResult] | None = None) -> None:
        """``behaviour`` bekommt die Rechnungsnummer; ohne Angabe: Erfolg."""
        self.behaviour, self.calls = behaviour or self._ok, []

    @staticmethod
    def _ok(number: str) -> FactoraResult:
        """Erfolg mit XML."""
        return FactoraResult("final", abs(hash(number)) % 1000, base64.b64encode(b"<x/>").decode(), None)

    def create_invoice(self, payload: dict[str, Any], key: str) -> FactoraResult:
        """Zeichnet auf und liefert das Verhalten."""
        number = payload["invoice_header"]["invoice_number"]
        self.calls.append((number, key))
        return self.behaviour(number)


def failing(status: int | None, message: str = "Fehler") -> Callable[[str], FactoraResult]:
    """Verhalten: wirft ``FactoraError`` mit dem Status."""
    def behave(number: str) -> FactoraResult:
        raise FactoraError(message, status)
    return behave
