"""Mapper-Ergänzungen: Zahlung, Leistungsdatum, Lieferadresse und SAP-Steuerkennzeichen am Kopf.

Auch hier wird nichts geraten: ein Wert ohne Eintrag in der Mandanten-Tabelle bricht den Beleg ab.
"""

from __future__ import annotations

from typing import Any

from sap_connector.config import TenantConfig
from sap_connector.errors import MappingError
from sap_connector.odata import parse_date, rows

_TRUE = {True, "X", "x", "true", "True", "1"}


def _lookup(table: dict[str, str], value: str, what: str, number: str) -> str:
    """Schlägt einen SAP-Code in der Tabelle nach; fehlt er, bricht der Beleg ab."""
    if value not in table:
        raise MappingError(number, f"{what} '{value}' fehlt in der Mapping-Tabelle.")
    return table[value]


def payment_fields(doc: dict[str, Any], cfg: TenantConfig, number: str) -> dict[str, str]:
    """Zahlungsart (BT-81) und Zahlungsbedingung (BT-20) über Tabellen; leer bleibt leer."""
    out: dict[str, str] = {}
    if doc.get("PaymentMethod"):
        out["payment_means_code"] = _lookup(cfg.payment_methods, doc["PaymentMethod"], "Zahlungsweg", number)
    if doc.get("CustomerPaymentTerms"):
        out["payment_terms"] = _lookup(cfg.payment_terms, doc["CustomerPaymentTerms"], "Zahlungsbedingung", number)
    return out


def apply_service_dates(doc: dict[str, Any], request: dict[str, Any]) -> None:
    """Leistungsdatum: einheitlich -> Kopf (BT-72), sonst je Position als Zeitraum (BT-134/135)."""
    raw = rows(doc.get("to_Item"))
    dates = [parse_date(i.get("ServicesRenderedDate")) for i in raw]
    if dates and len(set(dates)) == 1 and dates[0] is not None:
        request["invoice_header"]["delivery_date"] = dates[0].isoformat()
        return
    for item, day in zip(request["items"], dates):
        if day is not None:
            item["period_start"] = item["period_end"] = day.isoformat()


def shipping_block(doc: dict[str, Any], cfg: TenantConfig, number: str) -> dict[str, str] | None:
    """Lieferadresse (BG-13) aus dem Partner mit der konfigurierten Rolle und der Kundentabelle."""
    if not cfg.shipping_partner_function:
        return None
    found = [p for p in rows(doc.get("to_Partner")) if p.get("PartnerFunction") == cfg.shipping_partner_function]
    if not found:
        return None
    row = {**found[0], **cfg.customers.get(str(found[0].get("Customer")), {})}
    ship = {key: str(row.get(cfg.partner_fields[key]) or "") for key in ("name", "street", "zip", "city", "country")}
    missing = [k for k, v in ship.items() if not v]
    if missing:
        raise MappingError(number, f"Lieferadressfelder fehlen: {', '.join(missing)}.")
    return ship


def _not_export(item: dict[str, Any]) -> bool:
    """Position widerspricht einer Ausfuhr: Kategorie nicht G, oder ohne Kategorie mit positivem Satz."""
    category = item.get("tax_category_code", "")
    return category not in ("", "G") or (category == "" and item["vat_rate"] != "0.00")


def check_tax_flags(doc: dict[str, Any], items: list[dict[str, Any]], number: str) -> None:
    """SAP-Kennzeichen am Kopf dürfen dem Mapping nicht widersprechen; Dreiecksgeschäft wird abgelehnt."""
    if doc.get("IsEUTriangularDeal") in _TRUE:
        raise MappingError(number, "EU-Dreiecksgeschäft (IsEUTriangularDeal) wird nicht unterstützt.")
    if doc.get("IsExportDelivery") in _TRUE and any(_not_export(i) for i in items):
        raise MappingError(number, "SAP markiert eine Ausfuhrlieferung (IsExportDelivery), "
                                   "das Mapping liefert aber nicht für alle Positionen Kategorie G.")
