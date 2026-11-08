"""Sondiert die SAP-Hub-Sandbox nur lesend: deutsche Belege, Steuerkonditionen, Texte, Partneradressen.

Zugang aus der Umgebung: SAP_HUB_API_KEY (Pflicht), SAP_HUB_BASE_URL (optional). Der Key wird nie
ausgegeben. Ergebnis: ``sandbox_out/probe_summary.json`` (Feldnamen und Zähler, keine Rohdaten).

    python scripts/probe_sandbox.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import requests

BASE = os.environ.get("SAP_HUB_BASE_URL", "https://sandbox.api.sap.com/s4hanacloud")
BILLING = "/sap/opu/odata/sap/API_BILLING_DOCUMENT_SRV"
PARTNER = "/sap/opu/odata/sap/API_BUSINESS_PARTNER"
OUT = Path(__file__).resolve().parents[1] / "sandbox_out" / "probe_summary.json"


def get(path: str, headers: dict[str, str], **params: Any) -> tuple[int, Any]:
    """GET gegen die Sandbox; liefert Status und JSON (oder None)."""
    resp = requests.get(BASE + path, params={"$format": "json", **params}, headers=headers, timeout=90)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, None


def results(body: Any) -> list[dict[str, Any]]:
    """Ergebnisliste aus einer OData-V2-Antwort."""
    return (body or {}).get("d", {}).get("results", [])


def survey_documents(h: dict[str, str]) -> dict[str, Any]:
    """Zählt Belege nach Währung, Steuerabgangsland und Belegart (bis 200)."""
    status, body = get(f"{BILLING}/A_BillingDocument", h, **{"$top": 200,
        "$select": "BillingDocument,BillingDocumentType,TransactionCurrency,TaxDepartureCountry"})
    docs = results(body)
    return {"status": status, "anzahl": len(docs),
            "waehrung": Counter(d.get("TransactionCurrency") for d in docs),
            "steuerabgangsland": Counter(d.get("TaxDepartureCountry") for d in docs),
            "belegart": Counter(d.get("BillingDocumentType") for d in docs),
            "eur_oder_de": [d["BillingDocument"] for d in docs
                            if d.get("TransactionCurrency") == "EUR" or d.get("TaxDepartureCountry") == "DE"][:5]}


def describe_document(number: str, h: dict[str, str]) -> dict[str, Any]:
    """Fasst Steuerkonditionen, Texte und Partnerrollen eines Belegs zusammen (ohne Personendaten)."""
    status, body = get(f"{BILLING}/A_BillingDocument('{number}')", h,
                       **{"$expand": "to_Item,to_Item/to_PricingElement,to_Partner,to_Text"})
    doc = (body or {}).get("d", {})
    items = results(doc.get("to_Item"))
    taxes = Counter((e.get("ConditionType"), e.get("TaxCode"), e.get("ConditionRateValue"))
                    for i in items for e in results(i.get("to_PricingElement")) if e.get("TaxCode"))
    return {"beleg": number, "status": status, "positionen": len(items),
            "steuer_konditionen": [list(k) + [v] for k, v in taxes.items()],
            "text_ids": [t.get("LongTextID") for t in results(doc.get("to_Text"))],
            "partnerrollen": [p.get("PartnerFunction") for p in results(doc.get("to_Partner"))],
            "zero_vat_rsn": sorted({i.get("ZeroVATRsn") for i in items if i.get("ZeroVATRsn")})}


def probe_partner(customer: str, h: dict[str, str]) -> dict[str, Any]:
    """Prüft, ob der Business-Partner-Dienst Adresse und Name liefert (nur Feldnamen)."""
    status, body = get(f"{PARTNER}/A_BusinessPartner('{customer}')", h,
                       **{"$expand": "to_BusinessPartnerAddress"})
    bp = (body or {}).get("d", {})
    addr = results(bp.get("to_BusinessPartnerAddress"))
    return {"kunde": customer, "status": status, "felder_partner": sorted(k for k in bp if not k.startswith("to_")),
            "felder_adresse": sorted(addr[0]) if addr else [], "adressen": len(addr)}


def main() -> int:
    """Führt die Sondierung aus und schreibt die Zusammenfassung."""
    key = os.environ.get("SAP_HUB_API_KEY", "")
    if not key:
        print("FEHLER: SAP_HUB_API_KEY ist in diesem Fenster nicht gesetzt.", file=sys.stderr)
        return 1
    h = {"APIKey": key}
    summary = {"belege": survey_documents(h)}
    summary["beispiele"] = [describe_document(n, h) for n in summary["belege"]["eur_oder_de"]]
    summary["partner"] = probe_partner("17100001", h)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=dict), encoding="utf-8")
    print(f"geschrieben: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
