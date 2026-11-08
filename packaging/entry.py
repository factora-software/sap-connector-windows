"""Startpunkt der gebauten Datei (PyInstaller): ruft die Kommandozeile des Connectors auf."""

import sys

from sap_connector.cli import main

if __name__ == "__main__":
    sys.exit(main())
