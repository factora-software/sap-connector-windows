"""Ausgabe: XML und PDF aus der Factora-Antwort als Dateien ablegen."""

from __future__ import annotations

import base64
import re
from pathlib import Path

from sap_connector.factora_client import FactoraResult


def _safe(name: str) -> str:
    """Dateiname aus der Belegnummer (nur harmlose Zeichen)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def write_outputs(result: FactoraResult, out_dir: Path, billing_document: str) -> list[Path]:
    """Schreibt ``<Beleg>.xml`` und, falls geliefert, ``<Beleg>.pdf``; gibt die Pfade zurück."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for suffix, data in (("xml", result.xml_base64), ("pdf", result.pdf_base64)):
        if data:
            path = out_dir / f"{_safe(billing_document)}.{suffix}"
            path.write_bytes(base64.b64decode(data))
            written.append(path)
    return written
