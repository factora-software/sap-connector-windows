"""Mapper und Steuer-Mapping: Erfolgsfall und jeder Abbruchfall."""

from __future__ import annotations

import pytest

from sap_connector.errors import MappingError
from sap_connector.mapper import build_request


def test_success_maps_header_buyer_and_totals(doc, cfg):
    req = build_request(doc, cfg)
    head = req["invoice_header"]
    assert req["api_mode"] == "atomic_single_post"
    assert (head["invoice_number"], head["invoice_type"], head["currency"]) == ("90000001", "380", "EUR")
    assert head["buyer_reference"] == "04011000-12345-67"
    assert head["order_reference"] == "BEST-4711"
    assert req["buyer"]["name"] == "Beispiel Käufer AG"
    assert req["buyer"]["vat_id"] == "DE111111125"
    assert req["validation_totals"] == {"net_amount": "1100.00", "vat_amount": "197.00", "gross_amount": "1297.00"}
    assert req["seller_snapshot"]["name"] == "Beispiel Verkäufer GmbH"


def test_multiple_items_keep_order_rate_and_derive_category(doc, cfg):
    """Positive Sätze: nur der Satz geht raus, die Kategorie S leitet Factora ab."""
    first, second = build_request(doc, cfg)["items"]
    assert (first["description"], first["unit"], first["vat_rate"]) == ("Beratungsleistung", "HUR", "19.00")
    assert "tax_category_code" not in first and "tax_category_code" not in second
    assert (first["quantity"], first["unit_price_net"], first["sku"]) == ("10", "100.00", "BER-001")
    assert (second["unit"], second["vat_rate"], second["gtin"]) == ("H87", "7.00", "4006381333931")


def test_non_divisible_price_uses_price_base_quantity(doc, cfg):
    second = build_request(doc, cfg)["items"][1]
    assert (second["unit_price_net"], second["price_base_quantity"]) == ("100.00", "3")


def test_missing_leitweg_id_aborts(doc, cfg):
    doc["to_Text"] = {"results": []}
    with pytest.raises(MappingError, match="Leitweg-ID fehlt"):
        build_request(doc, cfg)


def test_zero_rate_without_table_entry_aborts(doc, cfg):
    """0 % ohne Eintrag: Abbruch, nie eine stille Kategorie (Invarianten 1, 2, 10)."""
    element = doc["to_Item"]["results"][0]["to_PricingElement"]["results"][1]
    element.update({"TaxCode": "ZZ", "ConditionRateValue": "0.000"})
    with pytest.raises(MappingError, match="'ZZ' mit 0 % fehlt in der Mapping-Tabelle"):
        build_request(doc, cfg)


def test_zero_rate_never_becomes_category_z(doc, cfg):
    """Auch ein ZZ-Kennzeichen mit 0 % ohne Eintrag liefert weder Z noch irgendeine Kategorie, sondern Abbruch."""
    element = doc["to_Item"]["results"][0]["to_PricingElement"]["results"][1]
    element["ConditionRateValue"] = "0.000"
    with pytest.raises(MappingError, match="mit 0 %"):
        build_request(doc, cfg)


def test_table_entry_without_category_or_supply_type_aborts(doc, cfg):
    element = doc["to_Item"]["results"][0]["to_PricingElement"]["results"][1]
    element.update({"TaxCode": "A5", "ConditionRateValue": "0.000"})
    cfg.tax_codes["A5"] = {}
    with pytest.raises(MappingError, match="gültige Kategorie"):
        build_request(doc, cfg)


def test_zero_rate_with_supply_type_only_sends_facts_not_category(doc, cfg):
    """K/G aus Tatsachen: nur supply_type, die Kategorie entscheidet Factora."""
    element = doc["to_Item"]["results"][0]["to_PricingElement"]["results"][1]
    element.update({"TaxCode": "A5", "ConditionRateValue": "0.000"})
    cfg.tax_codes["A5"] = {"supply_type": "goods"}
    item = build_request(doc, cfg)["items"][0]
    assert item["supply_type"] == "goods" and "tax_category_code" not in item and item["vat_rate"] == "0.00"


def test_zero_rate_tax_code_needs_its_zero_vat_reason(doc, cfg):
    item = doc["to_Item"]["results"][0]
    element = item["to_PricingElement"]["results"][1]
    element.update({"TaxCode": "A0", "ConditionRateValue": "0.000"})
    item["ZeroVATRsn"] = "R9"
    with pytest.raises(MappingError, match="ZeroVATRsn 'R9' fehlt"):
        build_request(doc, cfg)
    item["ZeroVATRsn"] = "R1"
    out = build_request(doc, cfg)["items"][0]
    assert (out["tax_category_code"], out["tax_exemption_reason_code"], out["vat_rate"]) == ("E", "VATEX-TEST", "0.00")


def test_item_without_tax_element_aborts(doc, cfg):
    doc["to_Item"]["results"][1]["to_PricingElement"] = {"results": []}
    with pytest.raises(MappingError, match="genau ein Steuer-Preiselement"):
        build_request(doc, cfg)


def test_unknown_unit_and_document_type_abort(doc, cfg):
    doc["to_Item"]["results"][0]["BillingQuantityUnit"] = "XX"
    with pytest.raises(MappingError, match="Mengeneinheit 'XX'"):
        build_request(doc, cfg)
    doc["to_Item"]["results"][0]["BillingQuantityUnit"] = "HR"
    doc["BillingDocumentType"] = "G2"
    with pytest.raises(MappingError, match="Belegart 'G2'"):
        build_request(doc, cfg)


def test_header_conditions_not_covered_by_items_abort(doc, cfg):
    doc["TotalNetAmount"] = "1000.00"
    with pytest.raises(MappingError, match="Kopfkonditionen"):
        build_request(doc, cfg)


def test_buyer_without_customer_table_entry_aborts(doc, cfg):
    """Der Partnersatz trägt keine Adresse; ohne Kundentabelle-Eintrag wird nichts geraten."""
    doc["to_Partner"]["results"][1]["Customer"] = "UNBEKANNT"
    with pytest.raises(MappingError, match="Käuferfelder fehlen"):
        build_request(doc, cfg)


def test_positive_rate_with_explicit_table_entry_uses_the_entry(doc, cfg):
    """Ein Eintrag gilt auch bei positivem Satz (z. B. ausdrücklich S); Factora prüft Satz gegen Kategorie."""
    cfg.tax_codes["A1"] = {"category": "S"}
    assert build_request(doc, cfg)["items"][0]["tax_category_code"] == "S"


def test_two_tax_elements_on_one_item_abort(doc, cfg):
    """Mehrere Steuerkonditionen (z. B. US-Jurisdiktionen) werden nicht addiert oder geraten."""
    elements = doc["to_Item"]["results"][0]["to_PricingElement"]["results"]
    elements.append(dict(elements[1]))
    with pytest.raises(MappingError, match="gefunden: 2"):
        build_request(doc, cfg)


def test_negative_tax_rate_aborts(doc, cfg):
    doc["to_Item"]["results"][0]["to_PricingElement"]["results"][1]["ConditionRateValue"] = "-19.000"
    with pytest.raises(MappingError, match="negativer Steuersatz"):
        build_request(doc, cfg)
