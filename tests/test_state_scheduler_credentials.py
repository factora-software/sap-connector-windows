"""Zustand, Zeitplan und Geheimnis-Speicher."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest

from sap_connector import scheduler, state as state_io
from sap_connector.credentials import SecretStore, resolve
from sap_connector.errors import ConnectorError


def test_state_roundtrip_and_missing_file(tmp_path):
    path = tmp_path / "data" / "state.json"
    assert state_io.load(path) == state_io.SyncState()
    state_io.save(path, state_io.SyncState("0090000009", {"0090000003": "Fehler"}, 4))
    assert state_io.load(path) == state_io.SyncState("0090000009", {"0090000003": "Fehler"}, 4)
    assert not path.with_suffix(".tmp").exists()


def test_windows_task_arguments_daily_and_hourly(tmp_path):
    daily = scheduler.windows_args(tmp_path, "daily", "02:30")
    assert daily[:2] == ["schtasks", "/Create"] and "DAILY" in daily and "02:30" in daily and "/F" in daily
    hourly = scheduler.windows_args(tmp_path, "hourly", "00:00")
    assert "HOURLY" in hourly and "/ST" not in hourly
    assert scheduler.task_name(tmp_path) == scheduler.task_name(tmp_path)


def test_cron_line_and_install_replaces_only_its_own_line(tmp_path):
    line = scheduler.cron_line(tmp_path, "daily", "02:30")
    assert line.startswith("30 02 * * * ") and line.endswith(f"{scheduler.MARKER} {tmp_path}")
    assert scheduler.cron_line(tmp_path, "hourly", "00:00").startswith("0 * * * * ")
    written = {}

    def runner(cmd, **kw):
        if cmd == ["crontab", "-l"]:
            old = f"0 1 * * * fremd\n99 * * * * alt {scheduler.MARKER} {tmp_path}\n"
            return subprocess.CompletedProcess(cmd, 0, stdout=old, stderr="")
        written["text"] = kw["input"]
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    scheduler.install(tmp_path, "daily", "02:30", platform="linux", runner=runner)
    text = written["text"]
    assert "0 1 * * * fremd" in text and "alt" not in text and text.count(scheduler.MARKER) == 1


def test_schtasks_failure_is_reported(tmp_path):
    def runner(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Zugriff verweigert")

    with pytest.raises(ConnectorError, match="schtasks fehlgeschlagen: Zugriff verweigert"):
        scheduler.install(tmp_path, "daily", "02:00", platform="win32", runner=runner)


def test_file_store_roundtrip_permissions_and_delete(tmp_path):
    secrets = tmp_path / "config" / "secrets.json"
    store = SecretStore(secrets, use_windows=False)
    assert store.get("k") is None
    store.set("k", "CHANGE_ME_WERT")
    assert store.get("k") == "CHANGE_ME_WERT"
    if sys.platform != "win32":
        assert (os.stat(secrets).st_mode & 0o777) == 0o600
    store.delete("k")
    assert store.get("k") is None


def test_resolve_prefers_environment_then_store_then_fails(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "config" / "secrets.json", use_windows=False)
    monkeypatch.delenv("X_TEST_SECRET", raising=False)
    with pytest.raises(ConnectorError, match="fehlt"):
        resolve(store, "s", "X_TEST_SECRET")
    store.set("s", "aus-speicher")
    assert resolve(store, "s", "X_TEST_SECRET") == "aus-speicher"
    monkeypatch.setenv("X_TEST_SECRET", "aus-umgebung")
    assert resolve(store, "s", "X_TEST_SECRET") == "aus-umgebung"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-Anmeldeinformationen")
def test_windows_credential_store_roundtrip_with_a_unique_throwaway_entry(tmp_path):
    root = tmp_path / f"home-{uuid.uuid4().hex}"
    store = SecretStore(root / "config" / "secrets.json", use_windows=True)
    try:
        assert store.get("probe") is None
        store.set("probe", "CHANGE_ME-ümlaut")
        assert store.get("probe") == "CHANGE_ME-ümlaut"
        assert not (root / "config" / "secrets.json").exists()
    finally:
        store.delete("probe")
    assert store.get("probe") is None
