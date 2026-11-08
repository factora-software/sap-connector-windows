"""Dauerbetrieb: Auswahl neuer Belege, Zustand, Fehler, Abbruchregeln, Probelauf."""

from __future__ import annotations

import pytest

from sap_connector import state as state_io
from sap_connector.errors import ConnectorError
from sap_connector.factora_client import FactoraResult
from sap_connector.home import Home, Settings
from sap_connector.sync import SyncDeps, format_report, run_sync
from tests.fakes import FakeFactora, FakeSap, failing

START = "0090000000"


@pytest.fixture
def home(tmp_path) -> Home:
    """Frischer Installationsordner."""
    h = Home(tmp_path / "sc")
    h.create()
    return h


def make(home, cfg, doc, numbers, factora=None, max_per_run=100, start=START):
    """Baut Abhängigkeiten mit Attrappen."""
    settings = Settings("https://sap.invalid", "u", start_after=start, max_per_run=max_per_run)
    sap, fac = FakeSap(numbers, doc), factora or FakeFactora()
    return SyncDeps(home, cfg, settings, sap, fac), sap, fac


def test_sends_new_documents_and_remembers_the_last_one(home, cfg, doc):
    deps, _, fac = make(home, cfg, doc, ["0090000001", "0090000002"])
    report = run_sync(deps)
    assert report.sent == ["0090000001", "0090000002"] and not report.failed
    assert [n for n, _ in fac.calls] == ["0090000001", "0090000002"]
    state = state_io.load(home.state_file)
    assert state.last_document == "0090000002" and state.sent_total == 2
    assert (home.out_dir / "0090000001.xml").exists()


def test_second_run_sends_nothing_again(home, cfg, doc):
    deps, _, fac = make(home, cfg, doc, ["0090000001"])
    run_sync(deps)
    assert run_sync(deps).sent == [] and len(fac.calls) == 1


def test_without_start_point_nothing_is_sent(home, cfg, doc):
    deps, sap, fac = make(home, cfg, doc, ["0090000001"], start="")
    with pytest.raises(ConnectorError, match="Kein Startpunkt"):
        run_sync(deps)
    assert fac.calls == [] and sap.fetched == []


def test_documents_at_or_before_the_start_point_are_never_sent(home, cfg, doc):
    deps, _, fac = make(home, cfg, doc, ["0089999999", START, "0090000001"])
    assert run_sync(deps).sent == ["0090000001"]
    assert [n for n, _ in fac.calls] == ["0090000001"]


def test_mapping_failure_is_recorded_and_the_run_continues(home, cfg, doc):
    deps, sap, _ = make(home, cfg, doc, ["0090000001", "0090000002"])
    original = sap.fetch
    sap.fetch = lambda n: {**original(n), "BillingDocumentType": "XX"} if n.endswith("1") else original(n)
    report = run_sync(deps)
    assert list(report.failed) == ["0090000001"] and report.sent == ["0090000002"]
    state = state_io.load(home.state_file)
    assert "0090000001" in state.failed and state.last_document == "0090000002"


def test_failed_document_is_retried_and_cleared_when_it_works(home, cfg, doc):
    state_io.save(home.state_file, state_io.SyncState(START, {"0090000005": "alte Meldung"}))
    deps, _, _ = make(home, cfg, doc, [])
    assert run_sync(deps).sent == ["0090000005"]
    assert state_io.load(home.state_file).failed == {}


@pytest.mark.parametrize("status", [401, 403, 500, 503, None])
def test_key_network_or_server_failure_aborts_without_marking_the_document(home, cfg, doc, status):
    fac = FakeFactora(failing(status, "kaputt"))
    deps, _, _ = make(home, cfg, doc, ["0090000001", "0090000002"], factora=fac)
    report = run_sync(deps)
    assert report.aborted and not report.failed and len(fac.calls) == 1
    state = state_io.load(home.state_file)
    assert state.failed == {} and state.last_document in ("", START)


def test_a_400_from_factora_is_a_document_failure_not_an_abort(home, cfg, doc):
    def behave(number: str) -> FactoraResult:
        if number.endswith("1"):
            return failing(400, "BR-DE-27")(number)
        return FactoraResult("final", 1, None, None)

    deps, _, _ = make(home, cfg, doc, ["0090000001", "0090000002"], factora=FakeFactora(behave))
    report = run_sync(deps)
    assert "0090000001" in report.failed and report.sent == ["0090000002"] and not report.aborted


def test_already_booked_counts_as_done_not_as_error(home, cfg, doc):
    fac = FakeFactora(lambda n: FactoraResult("already_booked", 7, None, None))
    report = run_sync(make(home, cfg, doc, ["0090000001"], factora=fac)[0])
    assert report.already == ["0090000001"] and not report.failed and not report.sent


def test_max_per_run_caps_the_batch(home, cfg, doc):
    deps, _, fac = make(home, cfg, doc, [f"009000000{i}" for i in range(1, 6)], max_per_run=2)
    assert len(run_sync(deps).sent) == 2 and len(fac.calls) == 2
    assert len(run_sync(deps).sent) == 2


def test_dry_run_sends_nothing_and_leaves_the_state_alone(home, cfg, doc):
    deps, _, fac = make(home, cfg, doc, ["0090000001"])
    report = run_sync(deps, dry_run=True)
    assert report.would_send == ["0090000001"] and fac.calls == []
    assert not home.state_file.exists()
    assert "Probelauf" in format_report(report, True)[0]


def test_retries_count_against_the_same_cap_as_new_documents(home, cfg, doc):
    state_io.save(home.state_file, state_io.SyncState(START, {"0090000005": "a", "0090000006": "b"}))
    deps, _, fac = make(home, cfg, doc, [f"009000001{i}" for i in range(5)], max_per_run=3)
    report = run_sync(deps)
    assert len(report.sent) == 3 and [n for n, _ in fac.calls][:2] == ["0090000005", "0090000006"]


def test_more_retries_than_the_cap_never_exceed_it(home, cfg, doc):
    failed = {f"009000000{i}": "alt" for i in range(1, 5)}
    state_io.save(home.state_file, state_io.SyncState(START, failed))
    deps, _, fac = make(home, cfg, doc, ["0090000099"], max_per_run=3)
    assert len(run_sync(deps).sent) == 3 and len(fac.calls) == 3 and "0090000099" not in [n for n, _ in fac.calls]
