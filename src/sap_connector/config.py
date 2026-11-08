"""Mandantenkonfiguration (JSON) und Zugangsdaten aus Umgebungsvariablen."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sap_connector.errors import ConnectorError

DEFAULT_FACTORA_URL = "https://console.factora.software/api/v1"
DEFAULT_PARTNER_FIELDS = {
    "name": "FullName",
    "street": "StreetName",
    "zip": "PostalCode",
    "city": "CityName",
    "country": "Country",
}


@dataclass(frozen=True)
class TenantConfig:
    """Alles, was je Mandant verschieden ist. Es gibt keine Standardwerte für Steuern."""

    tenant_scope: str
    seller: dict[str, Any] | None
    mandant_id: int | None
    profile: str
    tax_condition_types: list[str]
    tax_codes: dict[str, dict[str, Any]]
    zero_vat_reasons: dict[str, dict[str, Any]]
    units: dict[str, str]
    document_types: dict[str, str]
    customers: dict[str, dict[str, str]] = field(default_factory=dict)
    payment_methods: dict[str, str] = field(default_factory=dict)
    payment_terms: dict[str, str] = field(default_factory=dict)
    shipping_partner_function: str = ""
    leitweg_text_id: str = "EDDE"
    buyer_partner_function: str = "BP"
    partner_fields: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PARTNER_FIELDS))


def _validate(raw: dict[str, Any], path: Path) -> None:
    """Prüft Pflichtabschnitte und die Wahl Verkäufer-Snapshot oder Mandant."""
    for key in ("tenant_scope", "tax_condition_types", "units", "document_types"):
        if not raw.get(key):
            raise ConnectorError(f"Konfiguration {path}: Abschnitt '{key}' fehlt oder ist leer.")
    if bool(raw.get("seller")) == bool(raw.get("mandant_id")):
        raise ConnectorError(f"Konfiguration {path}: genau eines von 'seller' oder 'mandant_id' angeben.")


def load_config(path: Path) -> TenantConfig:
    """Liest die Mandantendatei; fehlende Pflichtabschnitte brechen ab."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    _validate(raw, path)
    return _build(raw)


def _build(raw: dict[str, Any]) -> TenantConfig:
    """Baut die Konfiguration aus dem geprüften JSON."""
    return TenantConfig(
        tenant_scope=raw["tenant_scope"],
        seller=raw.get("seller"),
        mandant_id=raw.get("mandant_id"),
        profile=raw.get("profile", "xrechnung"),
        tax_condition_types=raw["tax_condition_types"],
        tax_codes=raw.get("tax_codes", {}),
        zero_vat_reasons=raw.get("zero_vat_reasons", {}),
        units=raw["units"],
        document_types=raw["document_types"],
        customers=raw.get("customers", {}),
        payment_methods=raw.get("payment_methods", {}),
        payment_terms=raw.get("payment_terms", {}),
        shipping_partner_function=raw.get("shipping_partner_function", ""),
        leitweg_text_id=raw.get("leitweg_text_id", "EDDE"),
        buyer_partner_function=raw.get("buyer_partner_function", "BP"),
        partner_fields={**DEFAULT_PARTNER_FIELDS, **raw.get("partner_fields", {})},
    )


def env(name: str) -> str:
    """Liest eine Pflicht-Umgebungsvariable; fehlt sie, bricht der Aufruf ab."""
    value = os.environ.get(name, "")
    if not value:
        raise ConnectorError(f"Umgebungsvariable {name} ist nicht gesetzt.")
    return value
