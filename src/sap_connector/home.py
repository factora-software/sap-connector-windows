"""Installationsordner (``home``): Pfade und die nicht geheimen Einstellungen des Dauerbetriebs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from sap_connector.errors import ConnectorError

DEFAULT_FACTORA_URL = "https://console.factora.software/api/v1"


@dataclass(frozen=True)
class Settings:
    """Nicht geheime Einstellungen. Passwort, API-Key und SAP-Key stehen **nie** hier."""

    sap_base_url: str
    sap_user: str
    factora_base_url: str = DEFAULT_FACTORA_URL
    start_after: str = ""
    max_per_run: int = 100
    sap_uses_api_key: bool = False


class Home:
    """Ordnerstruktur: ``config/``, ``data/`` (Zustand), ``out/`` (E-Rechnungen), ``logs/``."""

    def __init__(self, root: Path) -> None:
        """Merkt sich den Wurzelordner."""
        self.root = root

    @property
    def settings_file(self) -> Path:
        """Datei der Einstellungen."""
        return self.root / "config" / "connector.json"

    @property
    def tenant_file(self) -> Path:
        """Mandanten-Konfiguration (Steuer-Tabelle, Verkäufer, Einheiten)."""
        return self.root / "config" / "tenant.json"

    @property
    def state_file(self) -> Path:
        """Zustand des Dauerbetriebs."""
        return self.root / "data" / "state.json"

    @property
    def out_dir(self) -> Path:
        """Ablage der erzeugten E-Rechnungen."""
        return self.root / "out"

    @property
    def secrets_file(self) -> Path:
        """Geheimnis-Datei (nur Linux; Windows nutzt die Anmeldeinformationen)."""
        return self.root / "config" / "secrets.json"

    def create(self) -> None:
        """Legt die Ordner an."""
        for sub in ("config", "data", "out", "logs"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    def save_settings(self, settings: Settings) -> None:
        """Schreibt die Einstellungen."""
        self.settings_file.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def load_settings(self) -> Settings:
        """Liest die Einstellungen; fehlt die Datei, wurde ``setup`` noch nicht gelaufen."""
        if not self.settings_file.exists():
            raise ConnectorError(f"Keine Einstellungen in {self.settings_file}: zuerst 'setup' ausführen.")
        return Settings(**json.loads(self.settings_file.read_text(encoding="utf-8")))
