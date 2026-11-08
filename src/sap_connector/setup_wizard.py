"""Setup-Assistent: Live-Key, Installationsordner, SAP-Zugang, Konfiguration, Startpunkt, Zeitplan.

Reihenfolge laut Auftrag: erst der Live-Key, dann der Installationspfad. Der Key wird zuerst geprüft (leerer,
kostenfreier Aufruf), aber erst nach der Wahl des Ordners abgelegt. Passwort und Key liegen im
Geheimnis-Speicher, nie in der Konfiguration. Der Assistent sendet keine Rechnung.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from sap_connector import installer, scheduler
from sap_connector.credentials import SecretStore
from sap_connector.errors import ConnectorError
from sap_connector.factora_client import FactoraClient
from sap_connector.home import DEFAULT_FACTORA_URL, Home, Settings
from sap_connector.sap_client import SapClient
from sap_connector.setup_prompts import Prompter, ask_required, parse_pairs, valid_time


def default_home() -> Path:
    """Vorschlag für den Installationsordner (im Benutzerordner)."""
    return Path.home() / "sap-connector"


def factora_url() -> str:
    """Factora-Adresse: Standard, nur für Tests über ``FACTORA_BASE_URL`` änderbar (keine Frage an den Kunden)."""
    return os.environ.get("FACTORA_BASE_URL") or DEFAULT_FACTORA_URL


def step_key(p: Prompter) -> str:
    """Schritt 1: Live-Key eingeben (verdeckt) und prüfen. Gespeichert wird er erst nach der Ordnerwahl."""
    p.say("Schritt 1 von 6: Factora Live-Key")
    key = p.secret("Live-Key (fa_live_…)")
    if not key.startswith("fa_"):
        raise ConnectorError("Das ist kein Factora-Key (beginnt mit fa_live_ oder fa_test_).")
    FactoraClient(factora_url(), key).probe_key()
    p.say("  Key akzeptiert (es wurde nichts angelegt).")
    return key


def step_home(p: Prompter, suggestion: Path) -> Home:
    """Schritt 2: Installationsordner wählen, anlegen und das Programm hineinkopieren."""
    p.say("Schritt 2 von 6: Wo soll der Connector installiert werden?")
    home = Home(Path(ask_required(p, "Installationsordner", str(suggestion))).expanduser())
    home.create()
    exe = installer.install_program(home)
    p.say(f"  Angelegt: {home.root}" + (f" (Programm: {exe})" if exe else ""))
    return home


def step_sap(p: Prompter, store: SecretStore) -> tuple[str, str, bool]:
    """Schritt 3: SAP-Zugang erfragen, testen und das Geheimnis ablegen."""
    p.say("Schritt 3 von 6: SAP (nur Lesezugriff auf API_BILLING_DOCUMENT_SRV)")
    url = ask_required(p, "SAP-Adresse (Basis-URL, https://…)")
    api_key = p.confirm("Anmeldung mit API-Key (nur Hub-Sandbox) statt Benutzer und Passwort?", default=False)
    user = "" if api_key else ask_required(p, "SAP-Benutzer")
    secret = p.secret("SAP-API-Key" if api_key else "SAP-Passwort")
    client = SapClient(url, user, secret) if not api_key else SapClient(url, headers={"APIKey": secret})
    client.list_documents(1)
    store.set("sap_secret", secret)
    p.say("  Verbindung zu SAP funktioniert, Zugang gespeichert.")
    return url, user, api_key


def step_tenant(p: Prompter) -> dict:
    """Schritt 4: Grunddaten des Kunden; die Steuer-Tabelle für 0 % bleibt leer (Steuerberater)."""
    p.say("Schritt 4 von 6: Verkäufer und Zuordnungen")
    seller = {"name": ask_required(p, "Firmenname"), "street": ask_required(p, "Straße"),
              "zip": ask_required(p, "PLZ"), "city": ask_required(p, "Ort"), "country": "DE",
              "vat_id": ask_required(p, "USt-IdNr."), "contact": {"phone": ask_required(p, "Telefon (mind. 3 Ziffern)"),
                                                                  "email": ask_required(p, "E-Mail für Rückfragen")}}
    if iban := p.ask("IBAN für Zahlungen (leer lassen, wenn keine)"):
        seller["iban"] = iban
    return {"tenant_scope": ask_required(p, "Kennung dieses Kunden (z. B. Firmenkürzel)"), "seller": seller,
            "tax_condition_types": [ask_required(p, "SAP-Konditionsart der Umsatzsteuer (z. B. MWST)")],
            "tax_codes": {}, "zero_vat_reasons": {}, **_mappings(p)}


def _mappings(p: Prompter) -> dict:
    """Einheiten und Belegarten (Pflicht, ohne Vorschlag: nichts wird geraten)."""
    units = parse_pairs(ask_required(p, "SAP-Einheiten (SAP=UN/ECE, z. B. PC=H87,HR=HUR)"), "Einheiten")
    types = parse_pairs(ask_required(p, "SAP-Belegarten (SAP=Factora, z. B. F2=380)"), "Belegarten")
    return {"units": units, "document_types": types}


def step_start(p: Prompter) -> str:
    """Schritt 5: Ab welcher Belegnummer gesendet wird (ohne Antwort wird nichts gesendet)."""
    p.say("Schritt 5 von 6: Startpunkt. Nur Belege NACH dieser Nummer werden gesendet (jede Rechnung kostet).")
    return ask_required(p, "Letzte Belegnummer, die NICHT mehr gesendet werden soll")


def step_schedule(p: Prompter, home: Home) -> str:
    """Schritt 6: Zeitplan anlegen (optional)."""
    p.say("Schritt 6 von 6: Zeitplan")
    if not p.confirm("Zeitplan jetzt anlegen?"):
        return "Kein Zeitplan angelegt: starten Sie 'sync' selbst."
    hourly = p.confirm("Stündlich ausführen (sonst täglich)?", default=False)
    at = "00:00" if hourly else ask_required(p, "Uhrzeit (HH:MM)", "02:00")
    if not hourly and not valid_time(at):
        raise ConnectorError(f"'{at}' ist keine Uhrzeit (HH:MM).")
    return scheduler.install(home.root, "hourly" if hourly else "daily", at, exe=installer.installed_exe(home))


def run_setup(p: Prompter, suggestion: Path | None = None) -> Home:
    """Führt alle Schritte aus. Bei einem Fehler bleibt nichts Halbfertiges stehen, das 'sync' starten könnte."""
    key = step_key(p)
    home = step_home(p, suggestion or default_home())
    store = SecretStore(home.secrets_file)
    try:
        url, user, uses_key = step_sap(p, store)
    except (ConnectorError, requests.RequestException) as exc:
        raise ConnectorError(f"Verbindungstest fehlgeschlagen, nichts wurde fertig eingerichtet: {exc}") from exc
    store.set("factora_key", key)
    tenant, start = step_tenant(p), step_start(p)
    home.tenant_file.write_text(json.dumps(tenant, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    home.save_settings(Settings(url, user, factora_url(), start, sap_uses_api_key=uses_key))
    p.say(step_schedule(p, home))
    p.say(f"Fertig. Nächste Schritte: Steuer-Tabelle (0 %) in {home.tenant_file} ergänzen, dann "
          "'check-mapping' mit Beispielbelegen, dann 'sync --dry-run'.")
    return home
