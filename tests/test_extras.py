"""Zahlung, Leistungsdatum, Lieferadresse, SAP-Kennzeichen am Kopf und der SapClient (gemockt)."""

from __future__ import annotations

import dataclasses

import pytest

from sap_connector.errors import MappingError, SapError
from sap_connector.mapper import build_request
from sap_connector.sap_client import SapClient


def test_payment_method_and_terms_use_the_tables(doc, cfg):
    doc.update({"PaymentMethod": "U", "CustomerPaymentTerms": "Z30"})
    cfg = dataclasses.replace(cfg, payment_methods={"U": "58"}, payment_terms={"Z30": "30 Tage netto"})
    head = build_request(doc, cfg)["invoice_header"]
    assert (head["payment_means_code"], head["payment_terms"]) == ("58", "30 Tage netto")


def test_unmapped_payment_method_aborts(doc, cfg):
    doc["PaymentMethod"] = "U"
    with pytest.raises(MappingError, match="Zahlungsweg 'U'"):
        build_request(doc, cfg)


def test_unmapped_payment_terms_abort(doc, cfg):
    doc["CustomerPaymentTerms"] = "Z30"
    with pytest.raises(MappingError, match="Zahlungsbedingung 'Z30'"):
        build_request(doc, cfg)


def test_uniform_service_date_goes_to_header(doc, cfg):
    for item in doc["to_Item"]["results"]:
        item["ServicesRenderedDate"] = "2026-10-15"
    req = build_request(doc, cfg)
    assert req["invoice_header"]["delivery_date"] == "2026-10-15"
    assert "period_start" not in req["items"][0]


def test_mixed_service_dates_become_item_periods(doc, cfg):
    first, second = doc["to_Item"]["results"]
    first["ServicesRenderedDate"], second["ServicesRenderedDate"] = "2026-10-15", "2026-10-20"
    req = build_request(doc, cfg)
    assert "delivery_date" not in req["invoice_header"]
    assert (req["items"][1]["period_start"], req["items"][1]["period_end"]) == ("2026-10-20", "2026-10-20")


def test_shipping_address_from_ship_to_partner(doc, cfg):
    doc["to_Partner"]["results"].append({"PartnerFunction": "WE", "Customer": "LIEF1"})
    customers = {**cfg.customers, "LIEF1": {"FullName": "Beispiel Lager", "StreetName": "Hafenweg 2",
                                           "PostalCode": "1000", "CityName": "Wien", "Country": "AT"}}
    cfg = dataclasses.replace(cfg, customers=customers, shipping_partner_function="WE")
    assert build_request(doc, cfg)["shipping"]["country"] == "AT"


def test_ship_to_partner_without_address_aborts(doc, cfg):
    doc["to_Partner"]["results"].append({"PartnerFunction": "WE", "Customer": "UNBEKANNT"})
    with pytest.raises(MappingError, match="Lieferadressfelder fehlen"):
        build_request(doc, dataclasses.replace(cfg, shipping_partner_function="WE"))


def test_eu_triangular_deal_is_rejected(doc, cfg):
    doc["IsEUTriangularDeal"] = "X"
    with pytest.raises(MappingError, match="Dreiecksgeschäft"):
        build_request(doc, cfg)


def test_export_flag_with_positive_rate_aborts(doc, cfg):
    """Ausfuhr-Kennzeichen, aber Positionen mit 19/7 %: Widerspruch, Abbruch."""
    doc["IsExportDelivery"] = "X"
    with pytest.raises(MappingError, match="Ausfuhrlieferung"):
        build_request(doc, cfg)


def test_export_flag_with_explicit_other_category_aborts(doc, cfg):
    doc["IsExportDelivery"] = "X"
    for item in doc["to_Item"]["results"]:
        item["to_PricingElement"]["results"][-1].update({"TaxCode": "A5", "ConditionRateValue": "0.000"})
    cfg.tax_codes["A5"] = {"category": "E", "exemption_reason_text": "Test"}
    with pytest.raises(MappingError, match="Ausfuhrlieferung"):
        build_request(doc, cfg)


def test_export_flag_with_derived_zero_rate_facts_passes(doc, cfg):
    doc["IsExportDelivery"] = "X"
    for item in doc["to_Item"]["results"]:
        item["to_PricingElement"]["results"][-1].update({"TaxCode": "A5", "ConditionRateValue": "0.000"})
    cfg.tax_codes["A5"] = {"supply_type": "goods"}
    assert all("tax_category_code" not in i for i in build_request(doc, cfg)["items"])


def test_buyer_email_goes_to_contact_when_configured(doc, cfg):
    customers = {k: {**v, "EmailAddress": "einkauf@beispiel.invalid"} for k, v in cfg.customers.items()}
    cfg = dataclasses.replace(cfg, customers=customers, partner_fields={**cfg.partner_fields, "email": "EmailAddress"})
    assert build_request(doc, cfg)["buyer"]["contact"] == {"email": "einkauf@beispiel.invalid"}


def test_buyer_without_email_sends_no_contact(doc, cfg):
    assert "contact" not in build_request(doc, cfg)["buyer"]


class _Resp:
    """Antwort-Attrappe für GET."""

    def __init__(self, status: int, body: dict) -> None:
        self.status_code, self._body = status, body

    def json(self) -> dict:
        return self._body


class _GetSession:
    """Zeichnet GET-Aufrufe auf."""

    def __init__(self, resp: _Resp) -> None:
        self.resp, self.calls, self.auth = resp, [], None

    def get(self, url, params, headers, timeout):
        self.calls.append((url, params, headers))
        return self.resp


def test_sap_client_builds_url_with_padded_key_expand_and_header():
    session = _GetSession(_Resp(200, {"d": {"BillingDocument": "0090000001"}}))
    client = SapClient("https://sap.invalid/", session=session, headers={"APIKey": "CHANGE_ME"})
    assert client.fetch("90000001")["BillingDocument"] == "0090000001"
    url, params, headers = session.calls[0]
    assert url.endswith("A_BillingDocument('0090000001')")
    assert "to_Item/to_PricingElement" in params["$expand"] and headers == {"APIKey": "CHANGE_ME"}


def test_sap_client_reports_non_200_and_lists_documents():
    with pytest.raises(SapError, match="404"):
        SapClient("https://sap.invalid", session=_GetSession(_Resp(404, {}))).fetch("1")
    listing = {"d": {"results": [{"BillingDocument": "90000000"}, {"BillingDocument": "90000001"}]}}
    assert SapClient("https://sap.invalid", session=_GetSession(_Resp(200, listing))).list_documents(2) == [
        "90000000", "90000001"]
