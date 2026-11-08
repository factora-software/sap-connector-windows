"""SAP-Client (nur lesen): OData ``API_BILLING_DOCUMENT_SRV`` oder JSON-Datei."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from sap_connector.errors import SapError
from sap_connector.odata import unwrap

SERVICE = "/sap/opu/odata/sap/API_BILLING_DOCUMENT_SRV"
EXPAND = "to_Item,to_Item/to_PricingElement,to_Partner,to_Text,to_PricingElement"


def load_file(path: Path) -> dict[str, Any]:
    """Liest einen Beleg im OData-Format aus einer JSON-Datei."""
    try:
        return unwrap(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise SapError(f"Belegdatei {path} nicht lesbar: {exc}") from exc


class SapClient:
    """Liest einen Fakturabeleg mit Basic-Auth. Schreibt nie nach SAP (nur GET)."""

    def __init__(self, base_url: str, user: str = "", password: str = "",
                 session: requests.Session | None = None,
                 headers: dict[str, str] | None = None) -> None:
        """Speichert Zugang und Session; ``headers`` z. B. für den API-Key der Hub-Sandbox."""
        self._base = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._headers = headers or {}
        if user:
            self._session.auth = (user, password)

    def list_documents(self, top: int = 5) -> list[str]:
        """Listet die ersten Belegnummern (zum Auffinden eines Testbelegs)."""
        params = {"$top": top, "$select": "BillingDocument,BillingDocumentType", "$format": "json"}
        resp = self._session.get(f"{self._base}{SERVICE}/A_BillingDocument", params=params,
                                 headers=self._headers, timeout=60)
        if resp.status_code != 200:
            raise SapError(f"SAP antwortet {resp.status_code} beim Auflisten.")
        results = resp.json().get("d", {}).get("results", [])
        return [r["BillingDocument"] for r in results]

    def list_since(self, after: str, types: list[str], top: int) -> list[str]:
        """Belegnummern nach ``after`` (aufsteigend), nur die gegebenen Belegarten, ohne stornierte Belege."""
        kinds = " or ".join(f"BillingDocumentType eq '{t}'" for t in types)
        flt = f"BillingDocument gt '{after.zfill(10)}' and ({kinds}) and BillingDocumentIsCancelled eq false"
        params = {"$filter": flt, "$orderby": "BillingDocument asc", "$top": top,
                  "$select": "BillingDocument,BillingDocumentType", "$format": "json"}
        resp = self._session.get(f"{self._base}{SERVICE}/A_BillingDocument", params=params,
                                 headers=self._headers, timeout=60)
        if resp.status_code != 200:
            raise SapError(f"SAP antwortet {resp.status_code} bei der Belegauswahl.")
        return [r["BillingDocument"] for r in resp.json().get("d", {}).get("results", [])]

    def fetch(self, billing_document: str) -> dict[str, Any]:
        """Holt Kopf, Positionen, Partner, Texte und Preiselemente eines Belegs."""
        key = billing_document.zfill(10)
        url = f"{self._base}{SERVICE}/A_BillingDocument('{key}')"
        resp = self._session.get(url, params={"$expand": EXPAND, "$format": "json"},
                                 headers=self._headers, timeout=60)
        if resp.status_code != 200:
            raise SapError(f"SAP antwortet {resp.status_code} für Beleg {key}.")
        return unwrap(resp.json())
