"""Programm in den Installationsordner kopieren (nur bei der gebauten Fassung, nicht bei ``pip install``)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from sap_connector.home import Home

PROGRAM_DIR = "program"


def is_frozen() -> bool:
    """``True``, wenn das Programm als gebaute Datei (PyInstaller) läuft."""
    return bool(getattr(sys, "frozen", False))


def installed_exe(home: Home) -> Path | None:
    """Pfad der installierten Programmdatei im Installationsordner, falls vorhanden."""
    exe = home.root / PROGRAM_DIR / Path(sys.executable).name
    return exe if is_frozen() and exe.exists() else None


def install_program(home: Home) -> Path | None:
    """Kopiert den Programmordner (Datei plus Bibliotheken) nach ``<Installationsordner>/program``.

    Gibt den Pfad der installierten Datei zurück; ohne gebaute Fassung ``None`` (dann läuft ``python -m``).
    Läuft das Programm schon aus dem Zielordner, wird nichts kopiert.
    """
    if not is_frozen():
        return None
    source, target = Path(sys.executable).resolve().parent, (home.root / PROGRAM_DIR).resolve()
    if source != target:
        shutil.copytree(source, target, dirs_exist_ok=True)
    return target / Path(sys.executable).name
