"""Mapper: Positionen eines SAP-Fakturabelegs -> ``items[]`` des Factora-Requests."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sap_connector.config import TenantConfig
from sap_connector.errors import MappingError
from sap_connector.odata import money, rows, to_decimal
from sap_connector.tax_mapping import TaxFacts, find_tax_element, resolve


def map_items(doc: dict[str, Any], cfg: TenantConfig, number: str) -> list[dict[str, Any]]:
    """Bildet alle Positionen ab; die Reihenfolge entspricht dem Beleg."""
    items = rows(doc.get("to_Item"))
    if not items:
        raise MappingError(number, "keine Positionen im Beleg.")
    return [_map_item(item, cfg, number) for item in items]


def _map_item(item: dict[str, Any], cfg: TenantConfig, number: str) -> dict[str, Any]:
    """Bildet eine Position ab (Menge, Preis, Steuer, Artikelkennungen)."""
    code, rate = find_tax_element(item, rows(item.get("to_PricingElement")), cfg, number)
    facts = resolve(item, code, rate, cfg, number)
    out = {
        "description": item.get("BillingDocumentItemText") or "",
        "unit": _unit(item, cfg, number),
        "vat_rate": money(facts.rate),
        **_price_fields(item, number),
        **_tax_text_fields(facts),
        **_optional_fields(item),
    }
    if not out["description"]:
        raise MappingError(number, f"Position {item.get('BillingDocumentItem')}: Text fehlt.")
    return out


def _unit(item: dict[str, Any], cfg: TenantConfig, number: str) -> str:
    """Mengeneinheit über die Mandanten-Tabelle; unbekannte Einheit bricht ab."""
    sap_unit = item.get("BillingQuantityUnit") or ""
    if sap_unit not in cfg.units:
        raise MappingError(number, f"Mengeneinheit '{sap_unit}' fehlt in der Mapping-Tabelle.")
    return cfg.units[sap_unit]


def _price_fields(item: dict[str, Any], number: str) -> dict[str, str]:
    """Menge und Preis. Factora nimmt den Einzelpreis nur mit 2 Stellen.

    Teilt sich der Positionsnettowert nicht glatt durch die Menge, wird der Positionswert
    als Preis je Basismenge (BT-149) gesendet: Menge x Preis / Basismenge = Nettowert.
    """
    qty, net = to_decimal(item.get("BillingQuantity")), to_decimal(item.get("NetAmount"))
    if qty is None or net is None or qty <= 0:
        raise MappingError(number, f"Position {item.get('BillingDocumentItem')}: Menge oder Nettobetrag fehlt/ungültig.")
    unit_price = net / qty
    if unit_price == unit_price.quantize(Decimal("0.01")):
        return {"quantity": format(qty, "f"), "unit_price_net": money(unit_price)}
    return {"quantity": format(qty, "f"), "unit_price_net": money(net),
            "price_base_quantity": format(qty, "f")}


def _tax_text_fields(facts: TaxFacts) -> dict[str, str]:
    """Befreiungsgrund und Lieferart, nur wenn die Mapping-Tabelle sie vorgibt."""
    out = {"tax_category_code": facts.category} if facts.category else {}
    if facts.exemption_code:
        out["tax_exemption_reason_code"] = facts.exemption_code
    if facts.exemption_text:
        out["tax_exemption_reason_text"] = facts.exemption_text
    if facts.supply_type:
        out["supply_type"] = facts.supply_type
    return out


def _optional_fields(item: dict[str, Any]) -> dict[str, str]:
    """Artikelnummer (BT-155) und GTIN (BT-157), wenn SAP sie liefert."""
    out = {}
    if item.get("Material"):
        out["sku"] = str(item["Material"])
    if item.get("InternationalArticleNumber"):
        out["gtin"] = str(item["InternationalArticleNumber"])
    return out
