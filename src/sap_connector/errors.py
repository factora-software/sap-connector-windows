"""Fehlerklassen des Connectors."""

from __future__ import annotations


class ConnectorError(Exception):
    """Basisklasse; die Meldung ist für Anwender gedacht."""


class MappingError(ConnectorError):
    """Ein Beleg lässt sich nicht eindeutig abbilden; es wird nichts gesendet."""

    def __init__(self, document: str, message: str) -> None:
        """Merkt sich die Belegnummer und baut die Meldung."""
        self.document = document
        super().__init__(f"Beleg {document}: {message}")


class SapError(ConnectorError):
    """Lesen aus SAP ist fehlgeschlagen."""


class FactoraError(ConnectorError):
    """Factora hat den Aufruf abgelehnt oder war nicht erreichbar."""

    def __init__(self, message: str, status: int | None = None) -> None:
        """``status`` ist der HTTP-Status der Antwort (``None`` bei Netzfehlern)."""
        self.status = status
        super().__init__(message)

    @property
    def is_auth_failure(self) -> bool:
        """401/403: Key ungültig, abgelaufen, ohne Scope oder IP nicht freigegeben."""
        return self.status in (401, 403)

    @property
    def stops_run(self) -> bool:
        """Ein Dauerlauf bricht ab statt weiterzumachen: Key ungültig, Netz weg oder Serverfehler (>= 500)."""
        return self.is_auth_failure or self.status is None or self.status >= 500
