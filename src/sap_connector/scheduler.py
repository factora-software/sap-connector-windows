"""Zeitplan für den Dauerbetrieb: Windows-Aufgabenplanung (``schtasks``) oder Cron unter Linux."""

from __future__ import annotations

import hashlib
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from sap_connector.errors import ConnectorError

Runner = Callable[..., subprocess.CompletedProcess]
MARKER = "# sap-connector"


def sync_command(home: Path, exe: Path | None = None) -> list[str]:
    """Kommando, das der Zeitplan ausführt: installierte Programmdatei, sonst ``python -m``."""
    if exe is not None:
        return [str(exe), "sync", "--home", str(home)]
    if getattr(sys, "frozen", False):
        return [sys.executable, "sync", "--home", str(home)]
    return [sys.executable, "-m", "sap_connector", "sync", "--home", str(home)]


def task_name(home: Path) -> str:
    """Eindeutiger Aufgabenname je Installationsordner."""
    return "SAP-Connector-" + hashlib.sha1(str(home).encode("utf-8")).hexdigest()[:8]


def windows_args(home: Path, schedule: str, at: str, exe: Path | None = None) -> list[str]:
    """``schtasks``-Aufruf: ``schedule`` ist ``daily`` (mit Uhrzeit HH:MM) oder ``hourly``."""
    base = ["schtasks", "/Create", "/TN", task_name(home), "/TR", subprocess.list2cmdline(sync_command(home, exe))]
    mode = ["/SC", "HOURLY"] if schedule == "hourly" else ["/SC", "DAILY", "/ST", at]
    return [*base, *mode, "/F"]


def cron_line(home: Path, schedule: str, at: str, exe: Path | None = None) -> str:
    """Cron-Zeile (mit Markierung, damit ein erneutes ``setup`` sie ersetzt statt verdoppelt)."""
    hour, minute = (at.split(":") + ["0"])[:2] if schedule != "hourly" else ("*", "0")
    cmd = shlex.join(sync_command(home, exe))
    log = shlex.quote(str(home / "logs" / "cron.log"))
    return f"{int(minute)} {hour} * * * {cmd} >> {log} 2>&1 {MARKER} {home}"


def _cron_install(home: Path, line: str, runner: Runner) -> None:
    """Schreibt die Crontab neu: eigene Zeilen dieses Ordners ersetzen, fremde unangetastet lassen."""
    current = runner(["crontab", "-l"], capture_output=True, text=True)
    keep = [ln for ln in (current.stdout or "").splitlines() if not ln.endswith(f"{MARKER} {home}")]
    done = runner(["crontab", "-"], input="\n".join([*keep, line]) + "\n", text=True, capture_output=True)
    if done.returncode != 0:
        raise ConnectorError(f"crontab konnte nicht geschrieben werden: {done.stderr.strip()}")


def install(home: Path, schedule: str, at: str, platform: str = sys.platform, runner: Runner = subprocess.run,
            exe: Path | None = None) -> str:
    """Legt den Zeitplan an und liefert eine Klartext-Beschreibung."""
    if platform == "win32":
        done = runner(windows_args(home, schedule, at, exe), capture_output=True, text=True)
        if done.returncode != 0:
            raise ConnectorError(f"schtasks fehlgeschlagen: {(done.stderr or done.stdout).strip()}")
        return f"Aufgabe '{task_name(home)}' in der Windows-Aufgabenplanung angelegt."
    _cron_install(home, cron_line(home, schedule, at, exe), runner)
    return "Cron-Eintrag angelegt (crontab -l zeigt ihn)."
