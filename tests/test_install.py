"""Klick-Start, Version, Programm kopieren, Zeitplan mit installierter Datei, stille Installation."""

from __future__ import annotations

import json
import shlex
import sys
import pytest

from sap_connector import __version__, cli, cli_batch, installer, scheduler, setup_wizard
from sap_connector.credentials import SecretStore
from sap_connector.errors import ConnectorError
from sap_connector.home import Home
from sap_connector.setup_prompts import ScriptedPrompter
from tests.test_setup import ANSWERS, FACTORA_KEY, SAP_SECRET, OkFactora, OkSap


def test_version_flag(capsys):
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"sap-connector {__version__}"


def test_double_click_without_arguments_starts_the_wizard_and_keeps_the_window_open(monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "is_frozen", lambda: True)
    monkeypatch.setattr(cli_batch, "setup_main", lambda argv: calls.append(("setup", argv)) or 0)
    monkeypatch.setattr(cli_batch, "_wait_for_enter", lambda: calls.append(("wait",)))
    assert cli_batch.dispatch([]) == 0
    assert calls == [("setup", []), ("wait",)]


def test_double_click_error_is_shown_and_the_window_stays_open(monkeypatch, capsys):
    waits = []
    monkeypatch.setattr(installer, "is_frozen", lambda: True)
    monkeypatch.setattr(cli_batch, "_wait_for_enter", lambda: waits.append(1))

    def boom(argv):
        raise ConnectorError("kaputt")

    monkeypatch.setattr(cli_batch, "setup_main", boom)
    assert cli_batch.dispatch([]) == 1 and waits == [1]
    assert "FEHLER: kaputt" in capsys.readouterr().err


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_closing_the_input_ends_cleanly_instead_of_crashing(monkeypatch, capsys, error):
    def interrupted(argv):
        raise error()

    monkeypatch.setattr(cli_batch, "setup_main", interrupted)
    assert cli_batch.dispatch(["setup"]) == 1
    assert "Abgebrochen" in capsys.readouterr().err


def test_without_a_built_file_no_arguments_is_not_a_double_click(monkeypatch):
    monkeypatch.setattr(installer, "is_frozen", lambda: False)
    assert cli_batch.dispatch([]) is None


def test_install_program_copies_the_program_folder_and_is_idempotent(tmp_path, monkeypatch):
    app = tmp_path / "download"
    (app / "_internal").mkdir(parents=True)
    (app / "sap-connector.exe").write_text("exe", encoding="utf-8")
    (app / "_internal" / "lib.dll").write_text("dll", encoding="utf-8")
    monkeypatch.setattr(installer, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", str(app / "sap-connector.exe"))
    home = Home(tmp_path / "ziel")
    home.create()
    exe = installer.install_program(home)
    assert exe == (home.root / "program" / "sap-connector.exe").resolve()
    assert (home.root / "program" / "_internal" / "lib.dll").read_text(encoding="utf-8") == "dll"
    assert installer.installed_exe(home) == home.root / "program" / "sap-connector.exe"
    assert installer.install_program(home) == exe


def test_install_program_does_nothing_for_the_pip_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "is_frozen", lambda: False)
    home = Home(tmp_path / "ziel")
    home.create()
    assert installer.install_program(home) is None and not (home.root / "program").exists()


def test_schedule_runs_the_installed_program_not_the_download_copy(tmp_path):
    exe = tmp_path / "program" / "sap-connector.exe"
    assert scheduler.sync_command(tmp_path, exe)[0] == str(exe)
    assert str(exe) in scheduler.windows_args(tmp_path, "daily", "02:00", exe)[5]
    assert scheduler.cron_line(tmp_path, "daily", "02:00", exe).startswith("0 02 * * * " + shlex.quote(str(exe)))


def test_scripted_prompter_uses_answers_and_environment_secrets(monkeypatch):
    p = ScriptedPrompter({"Installationsordner": "C:/x", "Zeitplan jetzt": False})
    assert p.ask("Installationsordner", "vorschlag") == "C:/x" and p.ask("Etwas anderes", "dflt") == "dflt"
    assert p.confirm("Zeitplan jetzt anlegen?") is False and p.confirm("Unbekannt", True) is True
    monkeypatch.delenv("FACTORA_API_KEY", raising=False)
    with pytest.raises(ConnectorError, match="FACTORA_API_KEY fehlt"):
        p.secret("Live-Key (fa_live_…)")
    monkeypatch.setenv("FACTORA_API_KEY", FACTORA_KEY)
    assert p.secret("Live-Key (fa_live_…)") == FACTORA_KEY


def test_key_comes_before_the_installation_folder(monkeypatch, tmp_path):
    order = []
    monkeypatch.setattr(setup_wizard, "step_key", lambda p: order.append("key") or FACTORA_KEY)
    monkeypatch.setattr(setup_wizard, "step_home", lambda p, s: order.append("pfad") or (_ for _ in ()).throw(ConnectorError("stop")))
    with pytest.raises(ConnectorError, match="stop"):
        setup_wizard.run_setup(ScriptedPrompter({}), tmp_path)
    assert order == ["key", "pfad"]


def test_silent_installation_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_wizard, "SapClient", OkSap)
    monkeypatch.setattr(setup_wizard, "FactoraClient", OkFactora)
    monkeypatch.setattr(setup_wizard, "SecretStore", lambda f: SecretStore(f, use_windows=False))
    monkeypatch.setenv("FACTORA_API_KEY", FACTORA_KEY)
    monkeypatch.setenv("SAP_PASSWORD", SAP_SECRET)
    target = tmp_path / "stille-installation"
    answers = {**ANSWERS, "Installationsordner": str(target), "Zeitplan jetzt": False}
    answers_file = tmp_path / "antworten.json"
    answers_file.write_text(json.dumps(answers), encoding="utf-8")
    assert cli.main(["setup", "--answers", str(answers_file)]) == 0
    home = Home(target)
    assert home.tenant_file.exists() and home.load_settings().start_after == "0090000000"
    assert SecretStore(home.secrets_file, use_windows=False).get("factora_key") == FACTORA_KEY
    assert FACTORA_KEY not in answers_file.read_text(encoding="utf-8")
