"""Steuer-Mapping: SAP-Steuerkennzeichen (+ ZeroVATRsn) -> Factora-Steuerfakten.

Regel: nichts wird geraten. Bei 0 % ohne Tabelleneintrag wird für den Beleg abgebrochen
(Factora-Invarianten 1, 2, 10). Satz und Kategorie prüft allein Factora.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sap_connector.config import TenantConfig
from sap_connector.errors import MappingError
from sap_connector.odata import to_decimal

CATEGORIES = {"S", "Z", "E", "AE", "K", "G", "O"}


@dataclass(frozen=True)
class TaxFacts:
    """Steuerangaben einer Position in Factora-Begriffen."""

    rate: Decimal
    category: str
    exemption_code: str = ""
    exemption_text: str = ""
    supply_type: str = ""


def _where(item: dict[str, Any]) -> str:
    """Positionsbezeichnung für Meldungen."""
    return f"Position {item.get('BillingDocumentItem', '?')}"


def find_tax_element(item: dict[str, Any], elements: list[dict[str, Any]],
                     cfg: TenantConfig, doc: str) -> tuple[str, Decimal]:
    """Sucht das eine Steuer-Preiselement der Position; liefert (TaxCode, Satz in %)."""
    hits = [e for e in elements if e.get("ConditionType") in cfg.tax_condition_types]
    if len(hits) != 1:
        raise MappingError(doc, f"{_where(item)}: erwartet genau ein Steuer-Preiselement "
                                f"{cfg.tax_condition_types}, gefunden: {len(hits)}.")
    code, rate = hits[0].get("TaxCode") or "", to_decimal(hits[0].get("ConditionRateValue"))
    if not code or rate is None:
        raise MappingError(doc, f"{_where(item)}: Steuer-Preiselement ohne TaxCode oder Satz.")
    return code, rate


def resolve(item: dict[str, Any], code: str, rate: Decimal,
            cfg: TenantConfig, doc: str) -> TaxFacts:
    """Steuerfakten einer Position. Positiver Satz ohne Eintrag: Factora leitet ``S`` selbst ab.

    Bei 0 % ist ein Tabelleneintrag Pflicht (Kategorie, oder nur ``supply_type`` für K/G aus Tatsachen);
    ohne Eintrag bricht der Beleg ab. Satz und Kategorie prüft Factora (eine Stelle, ein Entscheidungspfad).
    """
    if rate < 0:
        raise MappingError(doc, f"{_where(item)}: negativer Steuersatz {rate} %.")
    entry = cfg.tax_codes.get(code)
    if entry is None and rate > 0:
        return TaxFacts(rate, "")
    if entry is None:
        raise MappingError(doc, f"{_where(item)}: Steuerkennzeichen '{code}' mit 0 % fehlt in der Mapping-Tabelle.")
    entry = _with_zero_reason(entry, item, cfg, doc)
    _check_entry(entry, code, _where(item), doc)
    return TaxFacts(rate, entry.get("category", ""), entry.get("exemption_reason_code", ""),
                    entry.get("exemption_reason_text", ""), entry.get("supply_type", ""))


def _check_entry(entry: dict[str, Any], code: str, where: str, doc: str) -> None:
    """Ein Eintrag braucht eine gültige Kategorie oder (für K/G aus Tatsachen) ``supply_type``."""
    category = entry.get("category", "")
    if category not in CATEGORIES and not (category == "" and entry.get("supply_type")):
        raise MappingError(doc, f"{where}: Eintrag '{code}' braucht eine gültige Kategorie "
                                "oder (für K/G aus Tatsachen) supply_type.")


def _with_zero_reason(entry: dict[str, Any], item: dict[str, Any],
                      cfg: TenantConfig, doc: str) -> dict[str, Any]:
    """Ergänzt den Eintrag um den Befund aus ZeroVATRsn, wenn der Eintrag ihn verlangt."""
    if not entry.get("requires_zero_vat_reason"):
        return entry
    reason = item.get("ZeroVATRsn") or ""
    extra = cfg.zero_vat_reasons.get(reason)
    if extra is None:
        raise MappingError(doc, f"{_where(item)}: ZeroVATRsn '{reason}' fehlt in der Mapping-Tabelle.")
    return {**entry, **extra}
