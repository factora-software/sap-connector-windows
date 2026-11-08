"""Einrichtungshilfe: Beispielbelege lesen und die Lücken der Mandanten-Tabelle auflisten."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sap_connector.config import TenantConfig
from sap_connector.odata import rows, to_decimal


def _tax_rows(docs: list[dict[str, Any]], cfg: TenantConfig) -> Counter:
    """Zählt (Konditionsart, TaxCode, Satz, ZeroVATRsn) der Steuer-Preiselemente aller Positionen."""
    seen: Counter = Counter()
    for doc in docs:
        for item in rows(doc.get("to_Item")):
            for el in rows(item.get("to_PricingElement")):
                if el.get("ConditionType") in cfg.tax_condition_types:
                    rate = to_decimal(el.get("ConditionRateValue"))
                    seen[(el["ConditionType"], el.get("TaxCode") or "", rate, item.get("ZeroVATRsn") or "")] += 1
    return seen


def _candidates(docs: list[dict[str, Any]], cfg: TenantConfig) -> list[str]:
    """Konditionsarten mit TaxCode, die nicht als Steuerkondition konfiguriert sind (Hinweis zur Einrichtung)."""
    found = {el.get("ConditionType") for d in docs for i in rows(d.get("to_Item"))
             for el in rows(i.get("to_PricingElement")) if el.get("TaxCode") and el.get("ConditionType")}
    return sorted(found - set(cfg.tax_condition_types))


def _tax_lines(seen: Counter, cfg: TenantConfig) -> tuple[list[str], int]:
    """Eine Zeile je vorkommende Steuerkombination mit Status; zählt die Lücken."""
    lines, gaps = [], 0
    for (cond, code, rate, reason), count in sorted(seen.items(), key=lambda kv: (kv[0][1], str(kv[0][2]))):
        entry = cfg.tax_codes.get(code)
        if rate is not None and rate > 0 and entry is None:
            status = "ok (positiver Satz, Factora leitet S ab)"
        elif entry is None:
            status, gaps = "FEHLT (0 % braucht einen Eintrag)", gaps + 1
        elif entry.get("requires_zero_vat_reason") and reason not in cfg.zero_vat_reasons:
            status, gaps = f"FEHLT ZeroVATRsn '{reason}'", gaps + 1
        else:
            status = "ok (Eintrag vorhanden)"
        lines.append(f"  {code or '(leer)'} Satz {rate} % [{cond}] x{count}: {status}")
    return lines, gaps


def _value_gaps(docs: list[dict[str, Any]], cfg: TenantConfig) -> list[str]:
    """Einheiten, Belegarten, Zahlungswege und -bedingungen, die in der Konfiguration fehlen."""
    wanted = {"Mengeneinheit": ({i.get("BillingQuantityUnit") for d in docs for i in rows(d.get("to_Item"))}, cfg.units),
              "Belegart": ({d.get("BillingDocumentType") for d in docs}, cfg.document_types),
              "Zahlungsweg": ({d.get("PaymentMethod") for d in docs}, cfg.payment_methods),
              "Zahlungsbedingung": ({d.get("CustomerPaymentTerms") for d in docs}, cfg.payment_terms)}
    return [f"  FEHLT {what} '{v}'" for what, (values, table) in wanted.items()
            for v in sorted(x for x in values if x and x not in table)]


def check(docs: list[dict[str, Any]], cfg: TenantConfig) -> tuple[list[str], bool]:
    """Bericht über die Lücken der Tabelle für die gegebenen Belege; zweiter Wert: alles abgedeckt."""
    tax, gaps = _tax_lines(_tax_rows(docs, cfg), cfg)
    other = _value_gaps(docs, cfg)
    lines = [f"{len(docs)} Beleg(e) geprüft.", "Steuerkombinationen:", *(tax or ["  keine Steuer-Preiselemente gefunden"])]
    lines += ["Weitere Zuordnungen:", *(other or ["  alles vorhanden"])]
    hint = _candidates(docs, cfg)
    if hint or not tax:
        lines.append(f"Hinweis: Konditionsarten mit TaxCode in den Belegen: {', '.join(hint) or 'keine'} "
                     "(prüfen, ob eine davon die Umsatzsteuer trägt, und in tax_condition_types eintragen).")
    return lines, gaps == 0 and not other and bool(tax)
