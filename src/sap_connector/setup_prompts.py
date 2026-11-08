"""Ein- und Ausgabe des Setup-Assistenten (austauschbar für Tests) und kleine Eingabe-Parser."""

from __future__ import annotations

import getpass
import os
import re

from sap_connector.errors import ConnectorError


class Prompter:
    """Echte Eingabe auf der Konsole. Geheimnisse werden nicht angezeigt."""

    def say(self, text: str) -> None:
        """Gibt eine Zeile aus."""
        print(text)

    def ask(self, text: str, default: str = "") -> str:
        """Fragt nach einem Wert; leere Eingabe ergibt den Vorschlag."""
        suffix = f" [{default}]" if default else ""
        return input(f"{text}{suffix}: ").strip() or default

    def secret(self, text: str) -> str:
        """Fragt verdeckt (nichts wird beim Tippen angezeigt)."""
        return getpass.getpass(f"{text} (Eingabe bleibt unsichtbar): ").strip()

    def confirm(self, text: str, default: bool = True) -> bool:
        """Ja/Nein-Frage."""
        answer = input(f"{text} [{'J/n' if default else 'j/N'}]: ").strip().lower()
        return default if not answer else answer in ("j", "ja", "y", "yes")


class ScriptedPrompter(Prompter):
    """Stille Installation: Antworten aus einer JSON-Datei, Geheimnisse aus Umgebungsvariablen.

    Schlüssel der Datei sind Teilstrings der Fragen (z. B. ``"Installationsordner"``), Werte Text oder Wahrheitswerte.
    Geheimnisse: ``FACTORA_API_KEY``, ``SAP_PASSWORD``, ``SAP_API_KEY``. Fehlt eine Antwort, gilt der Vorschlag.
    """

    _ENV = {"Live-Key": "FACTORA_API_KEY", "SAP-Passwort": "SAP_PASSWORD", "SAP-API-Key": "SAP_API_KEY"}

    def __init__(self, answers: dict[str, object]) -> None:
        """Merkt die Antworten."""
        self.answers = answers

    def _lookup(self, text: str) -> object | None:
        """Antwort zur Frage (erster passender Schlüssel)."""
        return next((v for k, v in self.answers.items() if k in text), None)

    def ask(self, text: str, default: str = "") -> str:
        """Antwort aus der Datei, sonst der Vorschlag."""
        value = self._lookup(text)
        return default if value is None else str(value)

    def secret(self, text: str) -> str:
        """Geheimnis aus der Umgebung; fehlt es, bricht die stille Installation ab."""
        name = next((env for key, env in self._ENV.items() if key in text), "")
        value = os.environ.get(name, "") if name else ""
        if not value:
            raise ConnectorError(f"Stille Installation: Umgebungsvariable {name or '?'} fehlt für '{text}'.")
        return value

    def confirm(self, text: str, default: bool = True) -> bool:
        """Ja/Nein aus der Datei, sonst der Vorschlag."""
        value = self._lookup(text)
        return default if value is None else bool(value)


def ask_required(p: Prompter, text: str, default: str = "", attempts: int = 5) -> str:
    """Fragt, bis ein nicht leerer Wert kommt; nach ``attempts`` leeren Eingaben bricht der Assistent ab."""
    for _ in range(attempts):
        value = p.ask(text, default)
        if value:
            return value
        p.say("  Pflichtangabe.")
    raise ConnectorError(f"Pflichtangabe fehlt: {text}")


def parse_pairs(text: str, what: str) -> dict[str, str]:
    """Wandelt ``PC=H87,HR=HUR`` in ein Wörterbuch; ein Fehler nennt die Stelle."""
    pairs: dict[str, str] = {}
    for part in (x for x in text.split(",") if x.strip()):
        key, sep, value = part.partition("=")
        if not sep or not key.strip() or not value.strip():
            raise ConnectorError(f"{what}: '{part.strip()}' ist keine Zuordnung SAP=Wert.")
        pairs[key.strip()] = value.strip()
    if not pairs:
        raise ConnectorError(f"{what}: mindestens eine Zuordnung nötig.")
    return pairs


def valid_time(text: str) -> bool:
    """Uhrzeit ``HH:MM`` (24 Stunden)."""
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", text)
    return bool(match)
