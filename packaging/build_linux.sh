#!/bin/sh
# Baut die Linux-Datei in einem RHEL-8-kompatiblen Container (glibc 2.28), nicht auf dem eigenen Rechner:
#   docker run --rm -v <pfad>/sap_connector:/src:ro -v <pfad>/sap_connector/dist/linux_out:/out almalinux:8 sh /src/packaging/build_linux.sh
set -e
dnf -y -q install python3.11 python3.11-pip binutils
python3.11 -m pip install -q pyinstaller requests
cp -r /src /tmp/p && cd /tmp/p
python3.11 -m PyInstaller --noconfirm --onedir --name sap-connector --paths src --distpath dist --workpath build --specpath build packaging/entry.py
cp packaging/LIESMICH-linux.txt dist/sap-connector/LIESMICH.txt
VERSION=$(dist/sap-connector/sap-connector --version | awk '{print $2}')
tar czf "/out/sap-connector-linux-$VERSION.tar.gz" -C dist sap-connector
(cd /out && sha256sum "sap-connector-linux-$VERSION.tar.gz" > "sap-connector-linux-$VERSION.tar.gz.sha256")
echo "glibc des Build-Systems: $(ldd --version | head -1)"
echo "hoechste benoetigte glibc: $(objdump -T dist/sap-connector/sap-connector | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)"
