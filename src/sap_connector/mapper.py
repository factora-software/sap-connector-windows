"""Mapper: SAP-Fakturabeleg (OData) -> Request für ``POST /api/v1/invoices/atomic/``."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sap_connector.config import TenantConfig
from sap_connector.errors import MappingError
from sap_connector.mapper_extras import (apply_service_dates, check_tax_flags, payment_fields,
                                         shipping_block)
from sap_connector.mapper_items import map_items
from sap_connector.odata import money, parse_date, rows, to_decimal

TOLERANCE = Decimal("0.02")


def build_request(doc: dict[str, Any], cfg: TenantConfig) -> dict[str, Any]:
    """Baut den Atomic-Request. Wirft ``MappingError``, wenn etwas nicht eindeutig ist."""
    number = str(doc.get("BillingDocument") or "").strip()
    if not number:
        raise MappingError("?", "BillingDocument fehlt.")
    items = map_items(doc, cfg, number)
    totals = _totals(doc, number)
    _check_net_sum(items, totals["net_amount"], number)
    request: dict[str, Any] = {
        "api_mode": "atomic_single_post",
        "invoice_header": _header(doc, cfg, number),
        "validation_totals": totals,
        "buyer": _buyer(doc, cfg, number),
        "items": items,
    }
    request.update({"seller_snapshot": cfg.seller} if cfg.seller else {"mandant_id": cfg.mandant_id})
    return _with_extras(request, doc, cfg, number)


def _with_extras(request: dict[str, Any], doc: dict[str, Any], cfg: TenantConfig, number: str) -> dict[str, Any]:
    """Ergänzt Zahlung, Leistungsdatum und Lieferadresse und prüft die SAP-Kennzeichen am Kopf."""
    request["invoice_header"].update(payment_fields(doc, cfg, number))
    check_tax_flags(doc, request["items"], number)
    apply_service_dates(doc, request)
    shipping = shipping_block(doc, cfg, number)
    if shipping:
        request["shipping"] = shipping
    return request


def _header(doc: dict[str, Any], cfg: TenantConfig, number: str) -> dict[str, Any]:
    """Rechnungskopf: Nummer, Datum, Typ, Währung, Referenzen."""
    sap_type = doc.get("BillingDocumentType") or ""
    if sap_type not in cfg.document_types:
        raise MappingError(number, f"Belegart '{sap_type}' fehlt in der Mapping-Tabelle.")
    invoice_date = parse_date(doc.get("BillingDocumentDate"))
    if invoice_date is None or not doc.get("TransactionCurrency"):
        raise MappingError(number, "Belegdatum oder Währung fehlt.")
    header = {
        "invoice_number": number,
        "invoice_type": cfg.document_types[sap_type],
        "profile": cfg.profile,
        "invoice_date": invoice_date.isoformat(),
        "currency": doc["TransactionCurrency"],
        **_references(doc, cfg, number),
    }
    return header


def _references(doc: dict[str, Any], cfg: TenantConfig, number: str) -> dict[str, str]:
    """Leitweg-ID (BT-10), Bestellnummer (BT-13), Zahlungsangaben (BT-83, BT-89)."""
    out: dict[str, str] = {}
    leitweg = _header_text(doc, cfg.leitweg_text_id)
    if leitweg:
        out["buyer_reference"] = leitweg
    elif cfg.profile == "xrechnung":
        raise MappingError(number, f"Leitweg-ID fehlt (Kopftext {cfg.leitweg_text_id}); "
                                   "unter dem Profil xrechnung ist BT-10 Pflicht.")
    for sap, factora in (("PurchaseOrderByCustomer", "order_reference"),
                         ("PaymentReference", "remittance_information"),
                         ("SEPAMandate", "mandate_reference")):
        if doc.get(sap):
            out[factora] = str(doc[sap])
    return out


def _header_text(doc: dict[str, Any], text_id: str) -> str:
    """Liest den Kopftext mit der gegebenen Text-ID (Leerzeichen und Zeilenumbrüche entfernt)."""
    for row in rows(doc.get("to_Text")):
        if row.get("LongTextID") == text_id:
            return "".join(str(row.get("LongText") or "").split())
    return ""


def _partner_row(doc: dict[str, Any], cfg: TenantConfig, number: str) -> dict[str, Any]:
    """Der Käuferpartner (Rolle aus der Konfiguration), ergänzt um die Kundentabelle.

    Der Partnersatz des Belegs trägt keine Adresse (PartnerFunction, Customer, Supplier, ...),
    sie kommt deshalb aus ``customers`` der Konfiguration (Schlüssel: Kundennummer).
    """
    partners = [p for p in rows(doc.get("to_Partner")) if p.get("PartnerFunction") == cfg.buyer_partner_function]
    if len(partners) != 1:
        raise MappingError(number, f"erwartet genau einen Partner mit Rolle '{cfg.buyer_partner_function}', "
                                   f"gefunden: {len(partners)}.")
    return {**partners[0], **cfg.customers.get(str(partners[0].get("Customer")), {})}


def _buyer(doc: dict[str, Any], cfg: TenantConfig, number: str) -> dict[str, Any]:
    """Käufer: Adresse aus Partner/Kundentabelle, USt-IdNr. aus dem Kopf, E-Mail (BT-49) wenn gepflegt."""
    row = _partner_row(doc, cfg, number)
    fields = {k: v for k, v in cfg.partner_fields.items() if k != "email"}
    buyer: dict[str, Any] = {key: str(row.get(sap) or "") for key, sap in fields.items()}
    missing = [k for k, v in buyer.items() if not v]
    if missing:
        raise MappingError(number, f"Käuferfelder fehlen im Partner: {', '.join(missing)}.")
    if doc.get("VATRegistration"):
        buyer["vat_id"] = str(doc["VATRegistration"])
    if row.get(cfg.partner_fields.get("email", "")):
        buyer["contact"] = {"email": str(row[cfg.partner_fields["email"]])}
    return buyer


def _totals(doc: dict[str, Any], number: str) -> dict[str, str]:
    """Kontrollsummen aus dem Kopf (netto, Steuer, brutto)."""
    values = {key: to_decimal(doc.get(sap)) for key, sap in
              (("net_amount", "TotalNetAmount"), ("vat_amount", "TaxAmount"),
               ("gross_amount", "TotalGrossAmount"))}
    if any(v is None for v in values.values()):
        raise MappingError(number, "TotalNetAmount, TaxAmount oder TotalGrossAmount fehlt.")
    return {key: money(v) for key, v in values.items()}


def _check_net_sum(items: list[dict[str, Any]], net: str, number: str) -> None:
    """Positionen müssen den Kopf-Nettowert tragen; Kopfnachlässe werden nicht geraten."""
    total = sum((_line_net(i) for i in items), Decimal("0"))
    if abs(total - Decimal(net)) > TOLERANCE:
        raise MappingError(number, f"Summe der Positionen ({money(total)}) weicht vom Kopf-Nettowert "
                                   f"({net}) ab; Kopfkonditionen sind nicht abgebildet.")


def _line_net(item: dict[str, Any]) -> Decimal:
    """Nettowert einer abgebildeten Position (Menge x Preis / Basismenge)."""
    base = Decimal(item.get("price_base_quantity", "1"))
    return Decimal(item["quantity"]) * Decimal(item["unit_price_net"]) / base
