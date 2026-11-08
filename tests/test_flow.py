"""Factora-Aufruf (gemockt), Ausgabe und Wiederholung desselben Belegs."""

from __future__ import annotations

import base64
import json

import pytest

from sap_connector import cli
from sap_connector.errors import FactoraError
from sap_connector.factora_client import FactoraClient, idempotency_key
from sap_connector.mapper import build_request
from sap_connector.output import write_outputs
from tests.conftest import FIXTURES, FakeResponse, FakeSession

XML = b"<Invoice>test</Invoice>"
OK = {"valid": True, "data": {"id": 7, "status": "final", "xml_base64": base64.b64encode(XML).decode(),
                              "pdf_base64": base64.b64encode(b"%PDF-test").decode()}}
CONFLICT = {"valid": False, "data": {"id": 7, "status": "final"},
            "errors": [{"code": "conflict", "field": "", "message": "existiert bereits"}]}


def test_success_sends_bearer_and_writes_files(doc, cfg, tmp_path):
    session = FakeSession([FakeResponse(201, OK)])
    result = FactoraClient("https://x.invalid/api/v1", "CHANGE_ME", session).create_invoice(
        build_request(doc, cfg), idempotency_key(cfg.tenant_scope, "90000001"))
    call = session.calls[0]
    assert call["url"] == "https://x.invalid/api/v1/invoices/atomic/"
    assert call["headers"]["Authorization"] == "Bearer CHANGE_ME"
    paths = write_outputs(result, tmp_path, "90000001")
    assert [p.name for p in paths] == ["90000001.xml", "90000001.pdf"]
    assert paths[0].read_bytes() == XML


def test_repeat_uses_same_idempotency_key_and_replay_gives_same_files(doc, cfg, tmp_path):
    key = idempotency_key(cfg.tenant_scope, "90000001")
    assert key == idempotency_key(cfg.tenant_scope, "90000001")
    assert key != idempotency_key("anderer-mandant", "90000001")
    session = FakeSession([FakeResponse(201, OK), FakeResponse(201, OK, {"Idempotent-Replayed": "true"})])
    client = FactoraClient("https://x.invalid/api/v1", "CHANGE_ME", session)
    first = client.create_invoice(build_request(doc, cfg), key)
    second = client.create_invoice(build_request(doc, cfg), key)
    assert session.calls[0]["headers"]["Idempotency-Key"] == session.calls[1]["headers"]["Idempotency-Key"]
    assert session.calls[0]["json"] == session.calls[1]["json"]
    assert second.replayed and second.xml_base64 == first.xml_base64


def test_409_with_existing_invoice_is_not_an_error(doc, cfg):
    session = FakeSession([FakeResponse(409, CONFLICT)])
    result = FactoraClient("https://x.invalid/api/v1", "CHANGE_ME", session).create_invoice(
        build_request(doc, cfg), "k")
    assert (result.status, result.invoice_id, result.xml_base64) == ("already_booked", 7, None)


def test_400_is_reported_with_field_and_message(doc, cfg):
    body = {"valid": False, "data": None, "errors": [{"field": "buyer.zip", "message": "fehlt"}]}
    client = FactoraClient("https://x.invalid/api/v1", "CHANGE_ME", FakeSession([FakeResponse(400, body)]))
    with pytest.raises(FactoraError, match=r"HTTP 400.*buyer.zip: fehlt"):
        client.create_invoice(build_request(doc, cfg), "k")


def test_cli_aborts_without_calling_factora_on_mapping_error(tmp_path, monkeypatch, capsys):
    """Fehlendes Mapping: Exit 1 und der Factora-Client wird nie erzeugt."""
    broken = json.loads((FIXTURES / "billing_document.json").read_text(encoding="utf-8"))
    broken["d"]["to_Text"] = {"results": []}
    src = tmp_path / "beleg.json"
    src.write_text(json.dumps(broken), encoding="utf-8")
    monkeypatch.setattr(cli, "FactoraClient", lambda *a, **k: pytest.fail("Factora darf nicht aufgerufen werden"))
    code = cli.main(["--file", str(src), "--config", str(FIXTURES / "tenant.json"), "--out", str(tmp_path)])
    assert code == 1
    assert "Leitweg-ID fehlt" in capsys.readouterr().err


def test_cli_dry_run_prints_request(capsys):
    code = cli.main(["--file", str(FIXTURES / "billing_document.json"),
                     "--config", str(FIXTURES / "tenant.json"), "--dry-run"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["invoice_header"]["invoice_number"] == "90000001"


def test_kosit_verdict_from_response_is_exposed(doc, cfg):
    body = {"valid": True, "data": {**OK["data"], "validation": {"severity_max": "none", "severity_label": "Keine Befunde"}}}
    client = FactoraClient("https://x.invalid/api/v1", "CHANGE_ME", FakeSession([FakeResponse(201, body)]))
    result = client.create_invoice(build_request(doc, cfg), "k")
    assert result.validation["severity_label"] == "Keine Befunde"
