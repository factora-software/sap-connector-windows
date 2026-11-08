"""``--check-mapping``: zeigt Lücken der Tabelle und meldet vollständige Abdeckung."""

from __future__ import annotations

from sap_connector import cli
from sap_connector.mapping_check import check
from tests.conftest import FIXTURES


def test_complete_mapping_is_reported_ok(doc, cfg):
    lines, complete = check([doc], cfg)
    text = "\n".join(lines)
    assert complete and "positiver Satz, Factora leitet S ab" in text and "alles vorhanden" in text


def test_zero_rate_code_without_entry_is_a_gap(doc, cfg):
    doc["to_Item"]["results"][0]["to_PricingElement"]["results"][1].update({"TaxCode": "ZZ", "ConditionRateValue": "0.000"})
    lines, complete = check([doc], cfg)
    assert not complete and any("ZZ" in line and "FEHLT" in line for line in lines)


def test_missing_zero_vat_reason_unit_and_document_type_are_gaps(doc, cfg):
    item = doc["to_Item"]["results"][0]
    item["to_PricingElement"]["results"][1].update({"TaxCode": "A0", "ConditionRateValue": "0.000"})
    item["ZeroVATRsn"], item["BillingQuantityUnit"], doc["BillingDocumentType"] = "R9", "XX", "G2"
    text = "\n".join(check([doc], cfg)[0])
    assert "ZeroVATRsn 'R9'" in text and "Mengeneinheit 'XX'" in text and "Belegart 'G2'" in text


def test_unconfigured_tax_condition_type_is_hinted(doc, cfg):
    for item in doc["to_Item"]["results"]:
        for el in item["to_PricingElement"]["results"]:
            if el["ConditionType"] == "TESTMWST":
                el["ConditionType"] = "ANDERE"
    lines, complete = check([doc], cfg)
    assert not complete and any("Hinweis" in line and "ANDERE" in line for line in lines)


def test_cli_check_mapping_exit_codes(capsys):
    args = ["--file", str(FIXTURES / "billing_document.json"), "--config", str(FIXTURES / "tenant.json")]
    assert cli.main([*args, "--check-mapping"]) == 0
    assert "Beleg(e) geprüft" in capsys.readouterr().out
