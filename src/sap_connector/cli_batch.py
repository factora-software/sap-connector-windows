"""Kommandos des Dauerbetriebs: ``setup`` (Assistent) und ``sync`` (neue Belege senden)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sap_connector import __version__, installer
from sap_connector.config import load_config
from sap_connector.credentials import SecretStore, resolve
from sap_connector.errors import ConnectorError
from sap_connector.factora_client import FactoraClient
from sap_connector.home import Home
from sap_connector.sap_client import SapClient
from sap_connector.setup_prompts import Prompter, ScriptedPrompter
from sap_connector.setup_wizard import default_home, run_setup
from sap_connector.sync import SyncDeps, append_log, format_report, run_sync


def _home_arg(value: str | None) -> Home:
    """Installationsordner: Argument, sonst ``SAP_CONNECTOR_HOME``, sonst der Standard."""
    return Home(Path(value or os.environ.get("SAP_CONNECTOR_HOME") or default_home()).expanduser())


def _deps(home: Home) -> SyncDeps:
    """Baut die Abhängigkeiten eines Laufs aus Einstellungen, Konfiguration und Geheimnis-Speicher."""
    settings, cfg, store = home.load_settings(), load_config(home.tenant_file), SecretStore(home.secrets_file)
    sap_secret = resolve(store, "sap_secret", "SAP_API_KEY" if settings.sap_uses_api_key else "SAP_PASSWORD")
    sap = (SapClient(settings.sap_base_url, headers={"APIKey": sap_secret}) if settings.sap_uses_api_key
           else SapClient(settings.sap_base_url, settings.sap_user, sap_secret))
    factora = FactoraClient(settings.factora_base_url, resolve(store, "factora_key", "FACTORA_API_KEY"))
    return SyncDeps(home, cfg, settings, sap, factora)


def sync_main(argv: list[str]) -> int:
    """``sync``: neue Belege seit dem Startpunkt senden. Exit-Code 1 bei Fehlern oder Abbruch."""
    parser = argparse.ArgumentParser(prog="sap-connector sync", description=sync_main.__doc__)
    parser.add_argument("--home", help="Installationsordner (Standard: SAP_CONNECTOR_HOME oder ~/sap-connector)")
    parser.add_argument("--dry-run", action="store_true", help="nur anzeigen, was gesendet würde")
    args = parser.parse_args(argv)
    home = _home_arg(args.home)
    report = run_sync(_deps(home), args.dry_run)
    print("\n".join(format_report(report, args.dry_run)))
    if not args.dry_run:
        append_log(home, report)
    return 1 if report.failed or report.aborted else 0


def setup_main(argv: list[str]) -> int:
    """``setup``: der Assistent (Live-Key, Installationsordner, SAP, Konfiguration, Startpunkt, Zeitplan)."""
    parser = argparse.ArgumentParser(prog="sap-connector setup", description=setup_main.__doc__)
    parser.add_argument("--home", help="Vorschlag für den Installationsordner")
    parser.add_argument("--answers", help="JSON-Datei mit Antworten für eine stille Installation (Geheimnisse aus der Umgebung)")
    args = parser.parse_args(argv)
    prompter = ScriptedPrompter(json.loads(Path(args.answers).read_text(encoding="utf-8"))) if args.answers else Prompter()
    run_setup(prompter, Path(args.home).expanduser() if args.home else None)
    return 0


def _wait_for_enter() -> None:
    """Hält das Fenster offen (Doppelklick auf die Programmdatei), damit man die Meldung lesen kann."""
    try:
        input("Zum Beenden Enter drücken …")
    except EOFError:
        pass


def _run(argv: list[str]) -> int:
    """Führt ``setup`` oder ``sync`` aus; Fehler werden als Klartext gemeldet (Exit-Code 1)."""
    try:
        return (setup_main if argv[0] == "setup" else sync_main)(argv[1:])
    except ConnectorError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Abgebrochen. Es wurde nichts fertig eingerichtet.", file=sys.stderr)
        return 1


def dispatch(argv: list[str]) -> int | None:
    """Leitet ``--version``, ``setup`` und ``sync`` weiter; ``None``, wenn es das alte Einzel-Beleg-Kommando ist.

    Die gebaute Datei ohne Argumente (Doppelklick) startet den Assistenten und hält das Fenster offen.
    """
    if argv[:1] in (["--version"], ["-V"]):
        print(f"sap-connector {__version__}")
        return 0
    double_click = not argv and installer.is_frozen()
    argv = ["setup"] if double_click else argv
    if not argv or argv[0] not in ("setup", "sync"):
        return None
    code = _run(argv)
    if double_click:
        _wait_for_enter()
    return code
