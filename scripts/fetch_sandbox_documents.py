"""Holt Beispielbelege aus der SAP-Hub-Sandbox und legt sie als Roh-JSON ab (nur lesen).

Zugang aus der Umgebung: SAP_HUB_API_KEY (Pflicht), SAP_HUB_BASE_URL (optional).
Der Key wird nie ausgegeben oder gespeichert. Aufruf aus dem Ordner sap_connector:

    python scripts/fetch_sandbox_documents.py [Anzahl]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sap_connector.errors import ConnectorError  # noqa: E402
from sap_connector.sap_client import SapClient  # noqa: E402

DEFAULT_BASE = "https://sandbox.api.sap.com/s4hanacloud"  # nicht belegt, ggf. per SAP_HUB_BASE_URL ändern
OUT_DIR = Path(__file__).resolve().parents[1] / "sandbox_out"


def main() -> int:
    """Listet Belege der Sandbox und speichert die ersten als JSON in ``sandbox_out/``."""
    key = os.environ.get("SAP_HUB_API_KEY", "")
    if not key:
        print("FEHLER: SAP_HUB_API_KEY ist in diesem Fenster nicht gesetzt.", file=sys.stderr)
        return 1
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    client = SapClient(os.environ.get("SAP_HUB_BASE_URL", DEFAULT_BASE), headers={"APIKey": key})
    try:
        numbers = client.list_documents(count)
        OUT_DIR.mkdir(exist_ok=True)
        for number in numbers:
            path = OUT_DIR / f"{number}.json"
            path.write_text(json.dumps({"d": client.fetch(number)}, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"geschrieben: {path}")
    except ConnectorError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
