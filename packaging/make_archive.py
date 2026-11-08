"""Packt den gebauten Programmordner (PyInstaller) zu einem ZIP samt Prüfsumme (Windows).

    python packaging/make_archive.py <programmordner> <ausgabeordner>

Ergebnis: ``sap-connector-windows-<Version>.zip`` und ``….zip.sha256`` (Format wie ``sha256sum``).
Die Version steht nur in ``src/sap_connector/__init__.py``.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_version() -> str:
    """Liest ``__version__`` aus dem Paket (ohne es zu importieren)."""
    text = (ROOT / "src" / "sap_connector" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("__version__ nicht gefunden")
    return match.group(1)


def make_zip(program_dir: Path, out_dir: Path) -> tuple[Path, Path]:
    """Erzeugt ZIP (Wurzelordner ``sap-connector``) und ``.sha256``; legt ``LIESMICH.txt`` bei."""
    shutil.copy(ROOT / "packaging" / "LIESMICH-windows.txt", program_dir / "LIESMICH.txt")
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"sap-connector-windows-{read_version()}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(program_dir.rglob("*")):
            if file.is_file():
                zf.write(file, Path("sap-connector") / file.relative_to(program_dir))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.with_name(archive.name + ".sha256")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive, checksum


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    zip_path, sum_path = make_zip(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"{zip_path.name}  {sum_path.read_text(encoding='utf-8').split()[0][:16]}…")
