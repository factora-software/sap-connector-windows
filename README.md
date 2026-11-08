# SAP-Connector für Factora

Liest einen SAP-Fakturabeleg (OData `API_BILLING_DOCUMENT_SRV`, S/4HANA), baut daraus den
Factora-Sammelaufruf `POST /api/v1/invoices/atomic/`, ruft Factora mit Bearer-Key auf und legt
XML und PDF als Dateien ab. Er liest nur aus SAP (nur `GET`), schreibt nichts zurück und
importiert nichts aus `backend/`; Factora wird ausschließlich über die öffentliche HTTP-API
angesprochen.

> **Stand: nie gegen ein echtes SAP getestet.** Alles ist mit erfundenen Fixtures im
> OData-Format und mit einer Factora-Attrappe geprüft.

## Einrichtung

```bash
cd sap_connector
pip install -e ".[test]"
python -m pytest
```

Zugangsdaten nur aus Umgebungsvariablen (nie in Code, Fixtures oder Konfiguration):

| Variable | Zweck |
|---|---|
| `FACTORA_API_KEY` | Bearer-Key (`fa_test_…` für Sandbox) |
| `FACTORA_BASE_URL` | optional, Standard `https://console.factora.software/api/v1` |
| `SAP_BASE_URL`, `SAP_USER`, `SAP_PASSWORD` | nur für `--document` (live per OData) |

## Aufruf

```bash
# nur umwandeln, nichts senden
python -m sap_connector --file beleg.json --config tenant.json --dry-run
# Beleg aus Datei (OData-Format), an Factora senden, Dateien nach out/
python -m sap_connector --file beleg.json --config tenant.json --out out
# Lücken der Mandanten-Tabelle für Beispielbelege auflisten
python -m sap_connector --check-mapping --file beleg.json --config tenant.json
# Beleg live aus SAP lesen
python -m sap_connector --document 90000001 --config tenant.json
```

Ergebnis: `out/<Belegnummer>.xml` (die E-Rechnung) und `.pdf`, falls Factora eines erzeugt
(hängt an der Console-Einstellung „Factora erstellt die Rechnung visuell“). Exit-Code 1 mit
Klartext bei jedem Abbruch.

## Mandantenkonfiguration (`examples/tenant.example.json`)

Je Mandant eine JSON-Datei; im Repo nur Platzhalter (`CHANGE_ME…`).

- `tenant_scope`: Kennung des Mandanten; geht mit der Belegnummer in den Idempotency-Key ein
  (stabile UUID, dieselbe Nummer ergibt immer denselben Schlüssel).
- `seller` **oder** `mandant_id` (genau eines): Verkäuferdaten. Der SAP-Beleg liefert sie nicht.
- `tax_condition_types`: Konditionsarten der Preiselemente, die die Umsatzsteuer tragen.
- `tax_codes`: nur für Kennzeichen mit **0 %** nötig. Je Eintrag entweder `category` (S/Z/E/AE/K/G/O) mit optional
  `exemption_reason_code`/`exemption_reason_text`, oder nur `supply_type` (z. B. `goods`): dann sendet der Adapter keine
  Kategorie und Factora leitet `K`/`G` aus den Tatsachen ab (Lieferland, Leistungsdatum, Käufer-USt-IdNr.).
  `requires_zero_vat_reason: true` verlangt zusätzlich einen Eintrag in `zero_vat_reasons` für den `ZeroVATRsn` der Position.
  **Positive Sätze (19/7 %) brauchen keinen Eintrag:** der Adapter sendet nur den Satz, die Kategorie `S` leitet Factora
  ab und prüft den Satz gegen seine Länder-Tabelle. Ein Eintrag bei positivem Satz gilt als ausdrückliche Überschreibung.
- `units`: SAP-Einheit → UN/ECE-Code. `document_types`: SAP-Belegart → Factora-`invoice_type`.
- Optional, alle ohne Standardwert (Wert ohne Eintrag = Abbruch): `payment_methods` (SAP-`PaymentMethod` →
  UNCL-4461-Code), `payment_terms` (`CustomerPaymentTerms` → Text für BT-20), `shipping_partner_function`
  (z. B. `WE`; Lieferadresse aus Partner + `customers`), `partner_fields.email` (Käufer-E-Mail, BT-49).
- `leitweg_text_id` (Standard `EDDE`), `buyer_partner_function` (Standard `BP` = Bill-To, wie in der Sandbox),
  `customers` (Kundennummer → Adresse), `partner_fields` (Feldnamen der Adresse in `customers`).

**Es gibt keine Standardwerte für Steuern.** Ein Kennzeichen mit 0 % ohne Eintrag, ein Eintrag ohne Kategorie und
`supply_type`, ein negativer Satz, ein fehlender `ZeroVATRsn`-Eintrag, fehlende Leitweg-ID, Einheit, Belegart oder
Käuferadresse oder Positionen, die den Kopf-Nettowert nicht decken (Kopfkonditionen), brechen den Beleg ab; es geht nichts an
Factora. 0 % ergibt nie von selbst Kategorie Z. Satz und Kategorie prüft allein Factora (eine Stelle, kein zweiter
Entscheidungspfad im Adapter).

**Einrichtungshilfe:** `python -m sap_connector --check-mapping --file beleg1.json beleg2.json --config tenant.json`
liest Beispielbelege und listet vorkommende Kennzeichen, Sätze, `ZeroVATRsn`, Einheiten, Belegarten, Zahlwege und
-bedingungen mit Status; Lücken sind mit `FEHLT` markiert (Exit-Code 1). Findet es keine Steuer-Preiselemente, nennt es die
Konditionsarten mit `TaxCode` als Hinweis für `tax_condition_types`.

Preis: Factora nimmt `unit_price_net` mit zwei Nachkommastellen. Teilt sich der Positionswert nicht
glatt durch die Menge, sendet der Adapter den Positionswert als Preis je Basismenge
(`price_base_quantity` = Menge, BT-149), sodass Menge × Preis / Basismenge genau dem SAP-Wert entspricht.

## Dauerbetrieb und Setup-Assistent (Windows und Linux)

Für den Betrieb beim Kunden gibt es zwei Kommandos (der Einzel-Beleg-Aufruf oben bleibt unverändert):

```bash
python -m sap_connector setup      # Assistent: fragt Schritt für Schritt, testet, richtet ein
python -m sap_connector sync       # neue Belege seit dem Startpunkt senden (vom Zeitplan aufgerufen)
python -m sap_connector sync --dry-run   # nur anzeigen, was gesendet würde
```

**`setup`** (6 Schritte): (1) Factora-Key eingeben (verdeckt) und prüfen, (2) Installationsordner wählen, (3) SAP-Zugang erfragen und testen,
(4) Verkäufer, Einheiten, Belegarten, (5) Startpunkt, (6) Zeitplan anlegen. Passwort und
Key liegen **nicht** in der Konfiguration, sondern im Geheimnis-Speicher: unter **Windows** in den
Anmeldeinformationen des Benutzers (vom Betriebssystem geschützt), unter **Linux** in `config/secrets.json` mit
Rechten `0600` (nicht verschlüsselt, nur für den Benutzer lesbar). Eine Umgebungsvariable (`FACTORA_API_KEY`,
`SAP_PASSWORD`) hat Vorrang vor dem Speicher. Die Key-Prüfung sendet einen leeren Aufruf (kostenfrei, legt nichts an):
401/403 heißt Key unbrauchbar. Schlägt ein Verbindungstest fehl, wird nichts Halbfertiges eingerichtet.
Die Steuer-Tabelle für 0 % bleibt leer und wird vom Steuerberater in `config/tenant.json` ergänzt; danach
`--check-mapping` und `sync --dry-run`.

**`sync`** wählt Belege **nach** der Startnummer (nur die Belegarten der Konfiguration, ohne stornierte), sendet sie
der Reihe nach und merkt sich in `data/state.json` die letzte Nummer und die fehlgeschlagenen Belege. Regeln (jede
nutzbare Rechnung kostet):
- **Ohne Startpunkt wird nichts gesendet.** Belege bis zur Startnummer werden nie gesendet.
- Höchstens `max_per_run` Belege pro Lauf (Standard 100), Wiederholungen zählen mit.
- Ein Beleg mit Abbildungsfehler oder `400` von Factora wird als fehlgeschlagen gemerkt, der Lauf geht weiter, der
  Beleg wird beim nächsten Lauf erneut versucht. Exit-Code 1.
- Bei ungültigem Key (401/403), ausgefallenem Netz oder Serverfehler (5xx) **bricht der Lauf ab**, ohne den Beleg als
  fehlgeschlagen zu markieren oder weiterzuzählen.
- Derselbe Beleg zweimal ergibt dieselbe Rechnung (stabiler `Idempotency-Key`). `logs/sync.log` hat eine Zeile je Lauf.

Zeitplan: Windows-Aufgabenplanung (`schtasks`, täglich um HH:MM oder stündlich), Linux Cron-Eintrag (der Eintrag trägt
eine Markierung, ein erneutes `setup` ersetzt ihn, fremde Cron-Zeilen bleiben unberührt).

Geprüft (2026-11-08): alle Tests unter Windows und im Linux-Container (Python 3.14) grün; Windows-Tresor mit einem
Wegwerf-Eintrag, Linux-Dateirechte `0600` gemessen. **Nicht geprüft:** das echte Anlegen der Windows-Aufgabe (`schtasks`)
(auf diesem Rechner wurde keine Aufgabe angelegt), ein Lauf gegen ein echtes SAP-System.

## Installation als Programm (ohne Python, ohne Zertifikat)

Für Kunden gibt es je Betriebssystem **ein Paket mit allem drin**: Windows `sap-connector-windows-<Version>.zip`, Linux
`sap-connector-linux-<Version>.tar.gz` (jeweils mit `LIESMICH.txt` und Prüfsumme `*.sha256`). Ablauf für den Kunden:

1. Paket entpacken, **`sap-connector.exe` doppelklicken** (Linux: `./sap-connector`). Ohne Argumente startet die gebaute Datei den Assistenten
   und hält das Fenster offen.
2. Der Assistent fragt: **Live-Key** (verdeckt, wird geprüft) → **Installationspfad** → SAP-Zugang → Firmendaten und Zuordnungen →
   Startpunkt → Zeitplan. Das Programm wird in `<Pfad>/program` kopiert, der Zeitplan startet **diese** Kopie.
3. Fertig. Der Key liegt im Windows-Tresor bzw. (Linux) in einer Datei mit Rechten 0600, nie in der Konfiguration.

Die Datei ist **nicht signiert**: Windows zeigt beim ersten Start „Unbekannter Herausgeber“ (Weitere Informationen → Trotzdem ausführen),
Virenscanner können anschlagen. Eine Signatur ist keine Voraussetzung für die Funktion.

**Stille Installation** (für IT-Automatisierung): `sap-connector setup --answers antworten.json`; die Datei enthält die Antworten
(Schlüssel = Teil der Frage, z. B. `"Installationsordner"`), Geheimnisse kommen aus `FACTORA_API_KEY` und `SAP_PASSWORD`.
`sap-connector --version` zeigt die Version.

**Bauen** (nicht auf dem Kundenrechner): Windows: `python -m PyInstaller --onedir --name sap-connector --paths src packaging/entry.py`
(Build-Umgebung Python 3.13 mit `pyinstaller`, Ergebnis `dist/sap-connector`, danach ZIP). Linux: `packaging/build_linux.sh` in einem
AlmaLinux-8-Container (glibc 2.28), Ergebnis `.tar.gz` mit Prüfsumme.

Geprüft (2026-11-08) mit den gebauten Dateien: **Windows** (diese Maschine): `--version`, Probelauf, `check-mapping`, stille Installation
(echter Key-Test gegen die Factora-Sandbox, Programm kopiert, Geheimnisse nur im Windows-Tresor), `sync` mit dem **installierten** Programm ohne
Umgebungsvariablen (3 Belege gesendet, zweiter Lauf nichts Neues), falscher Key → Abbruch mit „Invalid API key“ ohne Zustandsänderung.
**Linux** (Container gegen ein Fake-SAP und die echte Factora-Sandbox): AlmaLinux 8 (glibc 2.28, mit **echtem Cron-Eintrag**), SUSE Linux Enterprise
Server 15 SP6 (SUSE-Basis-Container) und Debian 13 (glibc 2.41): jeweils Installation, Dateirechte 0600, Probelauf, `sync`. Die Linux-Datei benötigt
höchstens glibc 2.14.
**Nicht geprüft:** der Doppelklick selbst in einer echten Windows-Oberfläche (nur die Logik und der Start ohne Argumente sind getestet), das echte
Anlegen der Windows-Aufgabe (`schtasks`), SLES 15 vor SP6, Windows Server 2016 (nur Windows dieser Maschine), ein echtes SAP, SmartScreen- und
Virenscanner-Verhalten bei fremden Rechnern.

## Wiederholung

Gleicher Beleg → gleicher Idempotency-Key → Factora liefert die gespeicherte Antwort
(`Idempotent-Replayed`). Ist die Nummer schon gebucht (HTTP 409 mit Rechnung), meldet der
Adapter „bereits gebucht“ mit Exit-Code 0 und erzeugt nichts neu.

## Was belegt ist – und was nicht

Belegt (SAP Business Accelerator Hub, Schema-Ansicht `API_BILLING_DOCUMENT_SRV`, S/4HANA Cloud
Public Edition, abgelesen am 2026-11-08):
- Kopf-Navigation `to_Item`, `to_Partner`, `to_PricingElement`, `to_Text`; Position:
  `to_ItemText`, `to_Partner`, `to_PricingElement`. Die Kopffelder und Positionsfelder der Aufgabe
  (u. a. `ZeroVATRsn`, `NetAmount`, `ServicesRenderedDate`) gibt es.
- Preiselement: `ConditionType`, `ConditionRateValue`, `ConditionAmount`, `TaxCode` (u. a.). **Der
  Steuersatz kommt aus dem Preiselement der Umsatzsteuer-Konditionsart**, nicht aus Kopf/Position.
- Kopftext: `LongTextID`, `LongText`, `Language`.
- **Der Partnersatz trägt keine Adresse** (nur `PartnerFunction`, `Customer`, `Supplier`,
  `Personnel`, `ContactPerson`). Die Käuferadresse kommt deshalb aus `customers` der Konfiguration
  (Schlüssel Kundennummer). Eine Anbindung an den Business-Partner-Service fehlt noch.
- Factora-Seite (`docs/reference/atomic-invoice.md`, `tax-logic.md`, `api-overview.md`): Pflichtfelder,
  Bearer, Idempotency-Key, Antwort, 409-Verhalten.

**Gegen die Hub-Sandbox geprüft (3 Beispielbelege, US-Daten, 2026-11-08):**
- Struktur stimmt: `to_Item`, `to_Partner`, `to_PricingElement`, `to_Text`, Datum als `/Date(ms)/`.
- `ConditionRateValue` ist ein Prozentsatz: 4 + 2 + 1 + 1 % der Konditionen XR1–XR4 ergeben 8 %,
  und 4,21 = 8 % von 52,65 (`TaxAmount`).
- `TaxCode` steht an **allen** Preiselementen der Position (auch am Preis), nicht nur am Steuerelement.
- Positionen ohne Steuer (Beleg 90000001) tragen die Steuerkonditionen mit Satz 0 und `TaxCode` `O0`.
- Partnerrollen in der OData-Ausgabe sind `SP`, `BP`, `PY` (nicht `AG`/`RE`) → Standard jetzt `BP`.
- Keine Kopftexte und keine Kopf-Preiselemente in den Beispielbelegen.
- Einschränkung: US-Beispieldaten mit mehreren Steuerkonditionen (XR1–XR6, Jurisdiktion). Der deutsche
  Fall (eine MWST-Konditionsart, Satz 19/7) ist damit **nicht** belegt; der Adapter erwartet genau
  ein Steuerelement und bricht bei mehreren ab.

Gegen Factora geprüft (2026-11-08, synthetische Daten): Sandbox-Key → Status `sandbox`; Live-Key (Tenant-Test) →
Rechnung final, KoSIT „Keine Befunde“, XML + PDF; Wiederholung desselben Belegs → derselbe Idempotency-Key,
gleiche Rechnung, byte-identisches XML. Der erste Sandbox-Versuch scheiterte an einer Platzhalter-Telefonnummer
(BR-DE-27) und wurde vom Adapter mit Feld und Regel gemeldet.

Zusätzlich gegen die Factora-Sandbox geprüft: steuerfreie Position (`E` mit Text) angenommen; Ausfuhr (`G`, Lieferung
und Käufer in der Schweiz) angenommen; Käufer ohne USt-IdNr. und E-Mail abgelehnt (BT-49, Meldung kommt durch);
`K` (EU-Lieferung) abgelehnt, weil die erfundene USt-IdNr. die VIES-Prüfung nicht besteht und der Gelangensnachweis
fehlt: `K` ist damit nicht belegt. SAP-Kennzeichen `IsEUTriangularDeal` wird abgelehnt, `IsExportDelivery` muss zum
Mapping passen. Nicht gemappt, bewusst: `CustomerTaxClassification*`/`ProductTaxClassification*` (das Ergebnis steht im
`TaxCode` des Preiselements), `PayerParty`, `SoldToParty` (Rechnungsempfänger ist `BP`), `TaxDepartureCountry`.

Sondierung der Hub-Sandbox (`scripts/probe_sandbox.py`, 2026-11-08): alle 200 abrufbaren Belege sind USD und
Steuerabgangsland US (Belegarten F2: 192, G2: 5, FAZ: 3). **Es gibt dort keinen deutschen Beleg**; der deutsche
Steuerfall ist in der Sandbox nicht prüfbar. Der Business-Partner-Dienst (`A_BusinessPartner('17100001')`) liefert
Namensfelder (`BusinessPartnerFullName`, `OrganizationBPName1`), aber `to_BusinessPartnerAddress` kam für diesen
Kunden leer zurück; die Adresse per Dienst ist damit **nicht belegt**. Gutschriften (G2) kommen vor und sind nicht
unterstützt (Abbruch über `document_types`).

Umbau „Factora entscheidet“ (2026-11-08): Gegen den Test-Mandanten (Kleinunternehmer, Tenant 1) leitete Factora bei positivem
Satz ohne Kategorie `E` ab (BR-E-05) – richtig für dessen Profil. Deshalb trägt `examples/factora_run/tenant.json` `A1`/`A2`
ausdrücklich als `S`. **Beweis an einem regelbesteuerten Mandanten (lokal, Kopie der Test-Datenbank, danach gelöscht):**
ohne Eintrag und ohne Kategorie → Rechnung final, KoSIT ohne Befund, XML-Kategorie `S` (19/7 %); `E` aus der Tabelle → `E`;
`K` und `G` nur aus Tatsachen (`supply_type`, Lieferadresse, Leistungsdatum, Käufer-USt-IdNr.) → Factora leitete `K`
bzw. `G` ab, final, KoSIT ohne Befund. Hinweis: Lokal ist die VIES-Prüfung nicht belegt (die erfundene USt-IdNr. wurde dort
angenommen, in der prod-Sandbox abgelehnt); der `K`-Fall ist deshalb nur für die Ableitung belegt, nicht für VIES/Gelangensnachweis.

**Nicht belegt / offen:**
- Nie gegen ein deutsches System gelaufen; Konditionsart der MwSt und Steuerkennzeichen sind
  kundenspezifisch. On-Premise 2025 FPS02 ist nicht bestätigt.
- Text-ID `EDDE` (Leitweg-ID): in der Sandbox kein Text vorhanden, nicht geprüft.
- Gutschrift/Storno mit Bezug (BT-25) und Kopfkonditionen nicht abgebildet (Abbruch);
  Anzahlungen, Anhänge, Zahlungsbedingungen nicht umgesetzt.
- `SapClient` ist nur durch den Sandbox-Abruf geprüft, nicht durch einen automatischen Test.
- VATEX-Codes/-Texte im Mapping sind Sache des Mandanten und fachlich zu prüfen.
- Kein Zurückschreiben nach SAP.

Sandbox-Belege abrufen: `python scripts/fetch_sandbox_documents.py 3` (Variablen `SAP_HUB_API_KEY`,
optional `SAP_HUB_BASE_URL`; Ergebnis in `sandbox_out/`, nicht im Repo).

## Lauf gegen Factora (Sandbox)

Key nur in der eigenen PowerShell-Sitzung setzen (Sandbox-Key `fa_test_…`; Keys werden in der
Factora-Console angelegt, der Adapter erzeugt keine):

```powershell
$env:FACTORA_API_KEY = "CHANGE_ME"
$env:FACTORA_BASE_URL = "https://console.factora.software/api/v1"
python -m sap_connector --file examples/factora_run/beleg.json --config examples/factora_run/tenant.json --out out_sandbox
```

In der Sandbox ist `xml_base64` immer `null` und das PDF eine entwertete Vorschau
(`docs/reference/sandbox.md`); der Lauf prüft also Annahme und KoSIT-Urteil, nicht die XML-Datei.
Die Beispieldaten sind erfunden (Fixture-Beleg, Test-IBAN aus der öffentlichen Beispielliste).

## Lizenz

MIT, siehe [LICENSE](LICENSE).
