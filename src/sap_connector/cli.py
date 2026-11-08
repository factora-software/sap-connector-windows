"""Kommandozeile: Beleg lesen, abbilden, an Factora senden, Dateien ablegen."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sap_connector.cli_batch import dispatch
from sap_connector.config import DEFAULT_FACTORA_URL, env, load_config
from sap_connector.errors import ConnectorError
from sap_connector.factora_client import FactoraClient, idempotency_key
from sap_connector.mapper import build_request
from sap_connector.mapping_check import check as check_mapping
from sap_connector.output import write_outputs
from sap_connector.sap_client import SapClient, load_file


def _parser() -> argparse.ArgumentParser:
    """Argumente: Quelle (Datei oder SAP-Belegnummer), Konfiguration, Ausgabeordner."""
    p = argparse.ArgumentParser(prog="sap-connector", description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", type=Path, nargs="+", help="Beleg als JSON im OData-Format (mit --check-mapping mehrere)")
    src.add_argument("--document", help="Belegnummer; liest live per OData (SAP_BASE_URL, SAP_USER, SAP_PASSWORD)")
    p.add_argument("--config", type=Path, required=True, help="Mandantenkonfiguration (JSON)")
    p.add_argument("--out", type=Path, default=Path("out"), help="Ausgabeordner (Standard: out)")
    p.add_argument("--dry-run", action="store_true", help="nur den Request ausgeben, nichts senden")
    p.add_argument("--check-mapping", action="store_true", help="Lücken der Mandanten-Tabelle für die Belege auflisten")
    return p


def _read_document(args: argparse.Namespace) -> dict[str, Any]:
    """Beleg aus Datei oder live aus SAP."""
    if args.file:
        if len(args.file) != 1:
            raise ConnectorError("Ohne --check-mapping genau eine Datei angeben.")
        return load_file(args.file[0])
    return SapClient(env("SAP_BASE_URL"), env("SAP_USER"), env("SAP_PASSWORD")).fetch(args.document)


def run(args: argparse.Namespace) -> int:
    """Führt einen Beleg durch die Kette; gibt den Exit-Code zurück."""
    cfg = load_config(args.config)
    if args.check_mapping:
        return _check(args, cfg)
    payload = build_request(_read_document(args), cfg)
    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    number = payload["invoice_header"]["invoice_number"]
    client = FactoraClient(os.environ.get("FACTORA_BASE_URL") or DEFAULT_FACTORA_URL, env("FACTORA_API_KEY"))
    result = client.create_invoice(payload, idempotency_key(cfg.tenant_scope, number))
    return _report(result, args.out, number)


def _check(args: argparse.Namespace, cfg: Any) -> int:
    """Listet die Lücken der Mandanten-Tabelle; Exit-Code 1, wenn welche bestehen."""
    docs = [load_file(p) for p in args.file] if args.file else [_read_document(args)]
    lines, complete = check_mapping(docs, cfg)
    print(chr(10).join(lines))
    return 0 if complete else 1


def _report(result: Any, out_dir: Path, number: str) -> int:
    """Legt Dateien ab und meldet das Ergebnis."""
    if result.status == "already_booked":
        print(f"Beleg {number}: bei Factora bereits gebucht (Rechnung {result.invoice_id}); nichts erzeugt.")
        return 0
    for path in write_outputs(result, out_dir, number):
        print(f"geschrieben: {path}")
    print(f"Beleg {number}: Rechnung {result.invoice_id}, Status {result.status}.")
    if result.validation:
        print(f"KoSIT: {result.validation.get('severity_label')} ({result.validation.get('severity_max')})")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Einstiegspunkt; Fehler werden als Klartext gemeldet, Exit-Code 1."""
    routed = dispatch(sys.argv[1:] if argv is None else argv)
    if routed is not None:
        return routed
    try:
        return run(_parser().parse_args(argv))
    except ConnectorError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
