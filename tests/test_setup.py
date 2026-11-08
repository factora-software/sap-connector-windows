"""Setup-Assistent, Eingabe-Parser, Belegauswahl-URL, Key-Probe und die Kommandos setup/sync."""

from __future__ import annotations

import json

import pytest
import requests

from sap_connector import cli, cli_batch, setup_wizard
from sap_connector.config import load_config
from sap_connector.credentials import SecretStore
from sap_connector.errors import ConnectorError, FactoraError
from sap_connector.factora_client import FactoraClient
from sap_connector.home import Home, Settings
from sap_connector.sap_client import SapClient
from sap_connector.setup_prompts import parse_pairs, valid_time
from sap_connector.sync import SyncDeps
from tests.conftest import FakeResponse, FakeSession
from tests.fakes import FakeFactora, FakeSap
from tests.test_extras import _GetSession, _Resp

SAP_SECRET, FACTORA_KEY = "CHANGE_ME_SAP_PASSWORT", "fa_live_CHANGE_ME_KEY"


class FakePrompter:
    """Skriptierte Eingabe: ``answers`` nach Teilstring der Frage, ``secrets`` ebenso."""

    def __init__(self, answers: dict[str, str], secrets: dict[str, str], confirms: dict[str, bool] | None = None) -> None:
        """Merkt die Antworten."""
        self.answers, self.secrets, self.confirms, self.said = answers, secrets, confirms or {}, []

    def say(self, text: str) -> None:
        """Sammelt die Ausgabe."""
        self.said.append(text)

    def ask(self, text: str, default: str = "") -> str:
        """Antwort nach Teilstring, sonst der Vorschlag."""
        return next((v for k, v in self.answers.items() if k in text), default)

    def secret(self, text: str) -> str:
        """Geheime Antwort nach Teilstring."""
        return next(v for k, v in self.secrets.items() if k in text)

    def confirm(self, text: str, default: bool = True) -> bool:
        """Ja/Nein nach Teilstring, sonst Vorschlag."""
        return next((v for k, v in self.confirms.items() if k in text), default)


ANSWERS = {"Installationsordner": "", "SAP-Adresse": "https://sap.invalid", "SAP-Benutzer": "sapuser",
           "Factora-Adresse": "https://factora.invalid/api/v1", "Firmenname": "Beispiel GmbH", "Straße": "Weg 1",
           "PLZ": "10115", "Ort": "Berlin", "USt-IdNr.": "DE000000000", "Telefon": "030 1234567",
           "E-Mail": "rechnung@beispiel.invalid", "IBAN": "", "Kennung": "kunde-1", "Konditionsart": "MWST",
           "SAP-Einheiten": "PC=H87,HR=HUR", "SAP-Belegarten": "F2=380", "Letzte Belegnummer": "0090000000"}
SECRETS = {"SAP-Passwort": SAP_SECRET, "Live-Key": FACTORA_KEY}


class OkSap:
    """SAP-Attrappe: Verbindung funktioniert."""

    def __init__(self, *a, **k) -> None:
        """Nimmt beliebige Argumente."""

    def list_documents(self, top: int = 1) -> list[str]:
        """Erfolg."""
        return ["0090000001"]


class OkFactora:
    """Factora-Attrappe: Key wird akzeptiert."""

    def __init__(self, url: str, key: str) -> None:
        """Merkt nichts."""

    def probe_key(self) -> None:
        """Erfolg."""


@pytest.fixture
def wizard(monkeypatch, tmp_path):
    """Assistent mit Attrappen; Geheimnisse landen in einer Datei, nie im echten Windows-Tresor."""
    monkeypatch.setattr(setup_wizard, "SapClient", OkSap)
    monkeypatch.setattr(setup_wizard, "FactoraClient", OkFactora)
    monkeypatch.setenv("FACTORA_BASE_URL", "https://factora.invalid/api/v1")
    monkeypatch.setattr(setup_wizard, "SecretStore", lambda f: SecretStore(f, use_windows=False))
    monkeypatch.setattr(setup_wizard.scheduler, "install", lambda *a, **k: "Zeitplan angelegt (Test).")
    return tmp_path / "home"


def prompter(home, **override):
    """Prompter mit dem Installationsordner."""
    return FakePrompter({**ANSWERS, "Installationsordner": str(home), **override}, SECRETS)


def test_setup_writes_configuration_and_keeps_secrets_out_of_it(wizard):
    home = setup_wizard.run_setup(prompter(wizard))
    for file in (home.tenant_file, home.settings_file):
        text = file.read_text(encoding="utf-8")
        assert SAP_SECRET not in text and FACTORA_KEY not in text
    store = SecretStore(home.secrets_file, use_windows=False)
    assert store.get("sap_secret") == SAP_SECRET and store.get("factora_key") == FACTORA_KEY
    settings = home.load_settings()
    assert settings.start_after == "0090000000" and settings.factora_base_url == "https://factora.invalid/api/v1"
    cfg = load_config(home.tenant_file)
    assert cfg.units == {"PC": "H87", "HR": "HUR"} and cfg.document_types == {"F2": "380"} and cfg.tax_codes == {}


def test_a_rejected_factora_key_leaves_nothing_half_finished(wizard, monkeypatch):
    class Reject(OkFactora):
        def probe_key(self) -> None:
            raise FactoraError("Key abgelehnt", 401)

    monkeypatch.setattr(setup_wizard, "FactoraClient", Reject)
    with pytest.raises(ConnectorError, match="Key abgelehnt"):
        setup_wizard.run_setup(prompter(wizard))
    assert not wizard.exists(), "Der Key wird vor dem Ordner geprüft: bei Ablehnung entsteht kein Installationsordner"


def test_an_unreachable_sap_leaves_nothing_half_finished(wizard, monkeypatch):
    class Down(OkSap):
        def list_documents(self, top: int = 1) -> list[str]:
            raise requests.ConnectionError("kein Netz")

    monkeypatch.setattr(setup_wizard, "SapClient", Down)
    with pytest.raises(ConnectorError, match="Verbindungstest fehlgeschlagen"):
        setup_wizard.run_setup(prompter(wizard))
    assert not (wizard / "config" / "connector.json").exists()


def test_a_value_that_is_not_a_factora_key_is_refused(wizard):
    p = FakePrompter({**ANSWERS, "Installationsordner": str(wizard)}, {**SECRETS, "Live-Key": "kein-key"})
    with pytest.raises(ConnectorError, match="kein Factora-Key"):
        setup_wizard.run_setup(p)


def test_start_point_is_mandatory_so_nothing_is_billed_by_accident(wizard):
    p = prompter(wizard, **{"Letzte Belegnummer": ""})
    with pytest.raises(ConnectorError, match="Pflichtangabe fehlt: Letzte Belegnummer"):
        setup_wizard.run_setup(p)
    assert not (wizard / "config" / "connector.json").exists()


def test_bad_mapping_input_and_time_are_rejected(wizard):
    with pytest.raises(ConnectorError, match="keine Zuordnung"):
        setup_wizard.run_setup(prompter(wizard, **{"SAP-Einheiten": "PC H87"}))
    with pytest.raises(ConnectorError, match="keine Uhrzeit"):
        setup_wizard.run_setup(FakePrompter({**ANSWERS, "Installationsordner": str(wizard), "Uhrzeit": "25:99"}, SECRETS))


def test_declining_the_schedule_is_reported(wizard):
    p = FakePrompter({**ANSWERS, "Installationsordner": str(wizard)}, SECRETS, {"Zeitplan jetzt": False})
    setup_wizard.run_setup(p)
    assert any("Kein Zeitplan angelegt" in line for line in p.said)


def test_parsers():
    assert parse_pairs("PC=H87, HR = HUR", "x") == {"PC": "H87", "HR": "HUR"}
    for bad in ("", "PC", "=H87", "PC="):
        with pytest.raises(ConnectorError):
            parse_pairs(bad, "x")
    assert valid_time("02:30") and valid_time("2:05") and not valid_time("24:00") and not valid_time("abc")


def test_list_since_builds_the_filter_with_types_padding_and_no_cancelled():
    body = {"d": {"results": [{"BillingDocument": "0090000001"}]}}
    session = _GetSession(_Resp(200, body))
    numbers = SapClient("https://sap.invalid", session=session, headers={"APIKey": "CHANGE_ME"}).list_since("90000000", ["F2", "G2"], 5)
    _, params, headers = session.calls[0]
    assert numbers == ["0090000001"] and headers == {"APIKey": "CHANGE_ME"}
    assert "BillingDocument gt '0090000000'" in params["$filter"]
    assert "BillingDocumentType eq 'F2' or BillingDocumentType eq 'G2'" in params["$filter"]
    assert "BillingDocumentIsCancelled eq false" in params["$filter"] and params["$top"] == 5
    assert params["$orderby"] == "BillingDocument asc"


@pytest.mark.parametrize("status,ok", [(400, True), (422, True), (409, True), (401, False), (403, False), (200, False)])
def test_key_probe_accepts_only_authenticated_validation_answers(status, ok):
    client = FactoraClient("https://x.invalid/api/v1", "CHANGE_ME", FakeSession([FakeResponse(status, {})]))
    if ok:
        client.probe_key()
    else:
        with pytest.raises(FactoraError) as exc:
            client.probe_key()
        assert exc.value.status == status


def test_probe_never_sends_a_body_that_could_create_an_invoice():
    session = FakeSession([FakeResponse(400, {})])
    FactoraClient("https://x.invalid/api/v1", "CHANGE_ME", session).probe_key()
    assert session.calls[0]["json"] == {} and "Idempotency-Key" not in session.calls[0]["headers"]


def test_factora_error_flags():
    assert FactoraError("x", 401).is_auth_failure and FactoraError("x", 403).stops_run
    assert FactoraError("x", None).stops_run and FactoraError("x", 503).stops_run
    assert not FactoraError("x", 400).stops_run and not FactoraError("x", 409).stops_run


def prepared_home(tmp_path, cfg, doc, numbers, factora=None):
    """Installationsordner mit Einstellungen, damit ``sync`` ohne Netz läuft."""
    home = Home(tmp_path / "h")
    home.create()
    home.save_settings(Settings("https://sap.invalid", "u", start_after="0090000000"))
    deps = SyncDeps(home, cfg, home.load_settings(), FakeSap(numbers, doc), factora or FakeFactora())
    return home, deps


def test_sync_command_exit_codes_and_output(tmp_path, cfg, doc, monkeypatch, capsys):
    home, deps = prepared_home(tmp_path, cfg, doc, ["0090000001"])
    monkeypatch.setattr(cli_batch, "_deps", lambda h: deps)
    assert cli.main(["sync", "--home", str(home.root)]) == 0
    assert "gesendet 1" in capsys.readouterr().out and (home.root / "logs" / "sync.log").exists()
    assert cli.main(["sync", "--home", str(home.root), "--dry-run"]) == 0


def test_sync_command_fails_with_exit_1_when_a_document_fails(tmp_path, cfg, doc, monkeypatch, capsys):
    home, deps = prepared_home(tmp_path, cfg, doc, ["0090000001"])
    deps.cfg.document_types.clear()
    deps.cfg.document_types["ZZ"] = "380"
    monkeypatch.setattr(cli_batch, "_deps", lambda h: deps)
    assert cli.main(["sync", "--home", str(home.root)]) == 1
    assert "FEHLER 0090000001" in capsys.readouterr().out


def test_sync_without_setup_explains_what_to_do(tmp_path, capsys):
    assert cli.main(["sync", "--home", str(tmp_path / "leer")]) == 1
    assert "zuerst 'setup' ausführen" in capsys.readouterr().err


def test_the_old_single_document_command_still_works(capsys):
    from tests.conftest import FIXTURES
    code = cli.main(["--file", str(FIXTURES / "billing_document.json"), "--config", str(FIXTURES / "tenant.json"), "--dry-run"])
    assert code == 0 and json.loads(capsys.readouterr().out)["invoice_header"]["invoice_number"] == "90000001"
