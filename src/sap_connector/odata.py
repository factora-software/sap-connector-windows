"""Hilfen für das OData-Format (V2 und V4): Listen, Datum, Dezimalzahlen."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

_V2_DATE = re.compile(r"^/Date\((-?\d+)(?:[+-]\d+)?\)/$")


def unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """Entfernt den V2-Mantel ``{"d": ...}`` und liefert den Beleg-Datensatz."""
    node = payload.get("d", payload)
    if isinstance(node, dict) and isinstance(node.get("results"), list):
        rows = node["results"]
        if len(rows) != 1:
            raise ValueError(f"Erwartet genau einen Beleg, gefunden: {len(rows)}")
        return rows[0]
    return node


def rows(node: Any) -> list[dict[str, Any]]:
    """Liefert eine Navigationseigenschaft als Liste (V2 ``results`` oder V4-Liste)."""
    if node is None:
        return []
    if isinstance(node, dict):
        return list(node.get("results", []))
    return list(node)


def parse_date(value: Any) -> date | None:
    """Wandelt ``/Date(ms)/`` oder ISO-Text in ein Datum; leer ergibt ``None``."""
    if value in (None, ""):
        return None
    text = str(value)
    match = _V2_DATE.match(text)
    if match:
        stamp = int(match.group(1)) / 1000
        return datetime.fromtimestamp(stamp, tz=timezone.utc).date()
    return date.fromisoformat(text[:10])


def to_decimal(value: Any) -> Decimal | None:
    """Wandelt Zahl oder Text in ``Decimal``; leer ergibt ``None``."""
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"Keine Zahl: {value!r}") from exc


def money(value: Decimal) -> str:
    """Formatiert einen Betrag mit zwei Nachkommastellen (kaufmännisch gerundet)."""
    return format(value.quantize(Decimal("0.01"), rounding="ROUND_HALF_UP"), "f")
