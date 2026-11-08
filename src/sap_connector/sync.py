"""Dauerbetrieb: neue Belege seit der letzten Nummer holen, senden, Zustand und Fehler merken.

Sicherheitsregeln (jede nutzbare Rechnung kostet): ohne Startpunkt wird nichts gesendet; ein Lauf
verarbeitet höchstens ``max_per_run`` Belege; bei ungültigem Key, ausgefallenem Netz oder Serverfehler
bricht der Lauf ab, ohne den Beleg als fehlgeschlagen zu markieren oder den Zähler weiterzuschieben.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sap_connector import state as state_io
from sap_connector.config import TenantConfig
from sap_connector.errors import ConnectorError, FactoraError
from sap_connector.factora_client import FactoraClient, idempotency_key
from sap_connector.home import Home, Settings
from sap_connector.mapper import build_request
from sap_connector.output import write_outputs
from sap_connector.sap_client import SapClient
from sap_connector.state import SyncState


@dataclass
class SyncDeps:
    """Alles, was ein Lauf braucht (für Tests austauschbar)."""

    home: Home
    cfg: TenantConfig
    settings: Settings
    sap: SapClient
    factora: FactoraClient


@dataclass
class SyncReport:
    """Ergebnis eines Laufs."""

    sent: list[str] = field(default_factory=list)
    already: list[str] = field(default_factory=list)
    would_send: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    aborted: str = ""


def _todo(state: SyncState, deps: SyncDeps) -> tuple[list[str], list[str]]:
    """Belege dieses Laufs: erst die früher fehlgeschlagenen, dann die neuen (höchstens ``max_per_run`` zusammen)."""
    if not state.last_document:
        raise ConnectorError("Kein Startpunkt: 'setup' ausführen oder start_after setzen. Ohne Startpunkt wird nichts gesendet.")
    limit = deps.settings.max_per_run
    new = deps.sap.list_since(state.last_document, list(deps.cfg.document_types), limit)
    retries = sorted(state.failed)
    return retries[:limit], new[: max(limit - len(retries), 0)]


def _process(number: str, deps: SyncDeps, dry_run: bool) -> str:
    """Ein Beleg: lesen, abbilden, senden, ablegen. Rückgabe: ``sent``, ``already`` oder ``would``."""
    payload = build_request(deps.sap.fetch(number), deps.cfg)
    if dry_run:
        return "would"
    key = idempotency_key(deps.cfg.tenant_scope, payload["invoice_header"]["invoice_number"])
    result = deps.factora.create_invoice(payload, key)
    if result.status == "already_booked":
        return "already"
    write_outputs(result, deps.home.out_dir, number)
    return "sent"


def _record(report: SyncReport, state: SyncState, number: str, outcome: str) -> None:
    """Trägt ein Ergebnis in Bericht und Zustand ein."""
    {"sent": report.sent, "already": report.already, "would": report.would_send}[outcome].append(number)
    state.failed.pop(number, None)
    state.sent_total += 1 if outcome == "sent" else 0


def run_sync(deps: SyncDeps, dry_run: bool = False) -> SyncReport:
    """Ein Lauf. Bei ``dry_run`` wird nichts gesendet und der Zustand nicht verändert."""
    state = state_io.load(deps.home.state_file)
    if not state.last_document:
        state.last_document = deps.settings.start_after
    retries, new = _todo(state, deps)
    report = SyncReport()
    for number in [*retries, *new]:
        if not _step(number, number in new, deps, state, report, dry_run):
            break
        if not dry_run:
            state_io.save(deps.home.state_file, state)
    return report


def _step(number: str, is_new: bool, deps: SyncDeps, state: SyncState, report: SyncReport, dry_run: bool) -> bool:
    """Verarbeitet einen Beleg; ``False`` heißt: Lauf abbrechen (Key, Netz oder Serverfehler)."""
    try:
        _record(report, state, number, _process(number, deps, dry_run))
    except FactoraError as exc:
        if exc.stops_run:
            report.aborted = f"Beleg {number}: {exc}"
            return False
        state.failed[number] = str(exc)
        report.failed[number] = str(exc)
    except ConnectorError as exc:
        state.failed[number] = str(exc)
        report.failed[number] = str(exc)
    if is_new:
        state.last_document = max(state.last_document, number)
    return True


def format_report(report: SyncReport, dry_run: bool) -> list[str]:
    """Klartext-Zusammenfassung für Ausgabe und Protokoll."""
    head = "Probelauf (nichts gesendet)" if dry_run else "Lauf beendet"
    lines = [f"{head}: gesendet {len(report.sent)}, bereits gebucht {len(report.already)}, "
             f"zu senden {len(report.would_send)}, fehlgeschlagen {len(report.failed)}."]
    lines += [f"  FEHLER {n}: {m}" for n, m in sorted(report.failed.items())]
    if report.aborted:
        lines.append(f"  ABGEBROCHEN: {report.aborted}")
    return lines


def append_log(home: Home, report: SyncReport, now: datetime | None = None) -> None:
    """Eine Zeile je Lauf in ``logs/sync.log`` (nur Zähler und Belegnummern, keine Beleginhalte)."""
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    line = (f"{stamp} gesendet={len(report.sent)} bereits={len(report.already)} fehler={sorted(report.failed)} "
            f"abgebrochen={'ja' if report.aborted else 'nein'}")
    log = home.root / "logs" / "sync.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
