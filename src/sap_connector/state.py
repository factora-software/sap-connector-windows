"""Zustand des Dauerbetriebs: bis welcher Beleg verarbeitet wurde und was fehlgeschlagen ist."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SyncState:
    """``last_document``: höchste Belegnummer, die ein Lauf betrachtet hat. ``failed``: Beleg -> Meldung."""

    last_document: str = ""
    failed: dict[str, str] = field(default_factory=dict)
    sent_total: int = 0


def load(path: Path) -> SyncState:
    """Liest den Zustand; es gibt noch keinen = leerer Zustand."""
    if not path.exists():
        return SyncState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SyncState(raw.get("last_document", ""), dict(raw.get("failed", {})), int(raw.get("sent_total", 0)))


def save(path: Path, state: SyncState) -> None:
    """Schreibt den Zustand atomar (erst Nebendatei, dann ersetzen): ein Abbruch lässt die alte Datei heil."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"last_document": state.last_document, "failed": state.failed,
                               "sent_total": state.sent_total}, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
