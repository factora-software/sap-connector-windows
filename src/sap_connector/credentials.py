"""Geheimnisse (API-Key, SAP-Passwort) sicher ablegen und lesen.

Reihenfolge beim Lesen: Umgebungsvariable, dann der Speicher. Der Speicher ist unter Windows der
Anmeldeinformations-Tresor des Benutzers (durch das Betriebssystem geschützt), sonst eine Datei im
Installationsordner, die nur der Benutzer lesen darf (Rechte 0600, **nicht verschlüsselt**).
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path

from sap_connector.errors import ConnectorError

TARGET_PREFIX = "sap-connector/"
_CRED_TYPE_GENERIC, _CRED_PERSIST_LOCAL_MACHINE = 1, 2


class _Credential(ctypes.Structure):
    """Windows ``CREDENTIALW``."""

    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


def _target(home: str, name: str) -> str:
    """Name des Eintrags: je Installationsordner getrennt."""
    return f"{TARGET_PREFIX}{home}/{name}"


def _win_set(target: str, value: str) -> None:
    """Schreibt in den Windows-Tresor."""
    blob = value.encode("utf-16-le")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = _Credential(0, _CRED_TYPE_GENERIC, target, None, wintypes.FILETIME(), len(blob), buf,
                       _CRED_PERSIST_LOCAL_MACHINE, 0, None, None, "sap-connector")
    if not ctypes.windll.advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise ConnectorError("Windows-Anmeldeinformationen: Schreiben fehlgeschlagen.")


def _win_get(target: str) -> str | None:
    """Liest aus dem Windows-Tresor; fehlt der Eintrag, ``None``."""
    ptr = ctypes.POINTER(_Credential)()
    if not ctypes.windll.advapi32.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
        return None
    try:
        raw = ctypes.string_at(ptr.contents.CredentialBlob, ptr.contents.CredentialBlobSize)
        return raw.decode("utf-16-le")
    finally:
        ctypes.windll.advapi32.CredFree(ptr)


def _win_delete(target: str) -> None:
    """Löscht einen Eintrag im Windows-Tresor (nur eigene Einträge)."""
    ctypes.windll.advapi32.CredDeleteW(target, _CRED_TYPE_GENERIC, 0)


def _file_read(path: Path) -> dict[str, str]:
    """Liest die Geheimnis-Datei (leer, wenn es sie nicht gibt)."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _file_write(path: Path, data: dict[str, str]) -> None:
    """Schreibt die Datei und setzt Rechte nur für den Benutzer (0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(path, 0o600)


class SecretStore:
    """Speicher je Installationsordner."""

    def __init__(self, secrets_file: Path, use_windows: bool | None = None) -> None:
        """``use_windows`` erzwingt (Tests) oder verbietet den Windows-Tresor; Standard: automatisch."""
        self._file = secrets_file
        self._win = sys.platform == "win32" if use_windows is None else use_windows
        self._home = str(secrets_file.parent.parent)

    def set(self, name: str, value: str) -> None:
        """Legt ein Geheimnis ab."""
        if self._win:
            _win_set(_target(self._home, name), value)
        else:
            _file_write(self._file, {**_file_read(self._file), name: value})

    def get(self, name: str) -> str | None:
        """Liest ein Geheimnis oder ``None``."""
        if self._win:
            return _win_get(_target(self._home, name))
        return _file_read(self._file).get(name)

    def delete(self, name: str) -> None:
        """Entfernt ein Geheimnis (nur bei Deinstallation oder in Tests)."""
        if self._win:
            _win_delete(_target(self._home, name))
        else:
            data = _file_read(self._file)
            data.pop(name, None)
            _file_write(self._file, data)


def resolve(store: SecretStore, name: str, env_name: str) -> str:
    """Umgebungsvariable vor Speicher; fehlt beides, bricht der Lauf mit Klartext ab."""
    value = os.environ.get(env_name) or store.get(name)
    if not value:
        raise ConnectorError(f"Geheimnis '{name}' fehlt: {env_name} setzen oder 'setup' ausführen.")
    return value
