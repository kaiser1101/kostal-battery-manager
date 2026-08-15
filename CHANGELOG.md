# Changelog

## [0.11.4] - 2026-08-15

### Fixed
- **Verbrauchsprognose war bei duenner Datenlage unbrauchbar.**
  `get_average_consumption()` filtert nach Wochentag. Bei 7 Tagen Historie
  gibt es damit pro (Stunde, Wochentag) genau EINEN Messwert - es wird
  nichts gemittelt, und fehlt der Wert, griff sofort der pauschale
  Tagesdurchschnitt. Fuer Nachtstunden ist der um ein Vielfaches zu hoch.
  Jetzt wird zuerst ueber alle Wochentage gemittelt, bevor der Fallback
  greift.

### Added
- **Stundenweise Aufschluesselung des Ueberbrueckungsbedarfs** im Log und
  in den Plan-Diagnosen. Ohne sie war nicht erkennbar, ob die Prognose auf
  Messwerten beruht oder auf dem Fallback - und ein zu hoher Wert hebt den
  SOC-Deckel unnoetig an, womit der Hauptnutzen verloren geht.
- `get_sample_count()` im Learner: Anzahl Messwerte je Stunde.

### Changed
- **"Nachtbedarf" heisst jetzt "Ueberbrueckungsbedarf".** Der Wert umfasst
  die Spanne von Sonnenuntergang bis Sonnenaufgang und damit auch die
  Abend- und Morgenspitze - nicht nur die ruhigen Nachtstunden. Der alte
  Begriff legte das Gegenteil nahe.
  Entitaet: `sensor.<prefix>_overnight_need` -> `sensor.<prefix>_bridging_need`

## [0.11.3] - 2026-08-15

### Fixed
- **Echte Standortkoordinaten aus der Dokumentation entfernt.** README und
  CONFIGURATION.md enthielten die Koordinaten einer konkreten Anlage als
  Beispiel. Ersetzt durch neutrale Platzhalter.

## [0.11.2] - 2026-08-15

### Fixed
- Der SIGTERM-Handler ersetzte den von gunicorn, statt sich einzureihen.
  Sichtbar als `SystemExit: 0`-Traceback im Log beim Beenden. Das umging
  gunicorns geordnetes Herunterfahren der Worker. Jetzt wird nach dem
  Aufraeumen der vorherige Handler aufgerufen.

## [0.11.1] - 2026-08-15

### Added
- **Plan wird als Home-Assistant-Entitaeten veroeffentlicht**
  (`publish_ha_sensors: true`, Praefix ueber `ha_entity_prefix`):
  Ziel-SOC, Min-SOC, Ladeleistungsgrenze, Nachtbedarf, Fehlbetrag morgen,
  PV-Prognose und Status.
  - Der Recorder schreibt sie mit: Verlauf, Diagramme und Ausloeser fuer
    Automatisierungen, ohne dass das Add-on eine eigene Historie fuehren
    muss.
  - Der Status-Sensor traegt die Begruendung als Attribut - im Verlauf ist
    damit nachvollziehbar, WARUM eine Entscheidung fiel.
- `HomeAssistantClient.set_state()` zum Schreiben von Entitaeten.

### Documentation
- CONFIGURATION.md: Entitaetsliste, Beispieldiagramm fuer die
  Beobachtungsphase und eine Beispielautomatisierung fuer den Fall einer
  blockierten Batterie.

## [0.11.0] - 2026-08-15

### Verified
- **Die Leistungsregister 1038/1040 sind doch nutzbar.** Der Haltetest an
  realer Hardware zeigt: ein Ladelimit von 2000 W hielt 3 Minuten ohne
  Nachschreiben unveraendert. Die frueheren "abgelehnt"-Ergebnisse kamen
  daher, dass der Registertest nur 100 W unter den Ist-Wert ging - zu nah
  an dem Bereich, in dem die Firmware selbst schreibt.
- Damit sind alle vier Hebel des urspruenglichen Entwurfs nutzbar,
  inklusive der Ladeleistungs-Drosselung.

### Changed
- **Nachtsperre entfernt.** Sie setzte ausserhalb der PV-Stunden 0 W, um
  Netzladung zu verhindern - schuetzte aber vor nichts, da Netzladung nur
  ueber Setpoints entsteht, die diese Strategie nie schreibt. Und ein
  0-W-Limit persistiert: ein Ausfall haette die Batterie dauerhaft
  gesperrt.
- **Kein 0-W-Grenzwert mehr an irgendeiner Stelle.** Laden wird ueber den
  SOC-Deckel gestoppt, Entladen ueber die SOC-Untergrenze - beides
  wirksam, aber ungefaehrlich, wenn es haengen bleibt.
- Der Sicherheitsfall stoppt das Entladen jetzt ueber `min_soc` statt ueber
  ein 0-W-Entladelimit.

### Added
- **Freigabe der Grenzwerte beim Beenden** (`atexit` + SIGTERM): Alle vier
  Register werden auf die beim Start vorgefundenen Werte zurueckgesetzt.
  Ohne das koennte eine Drosselung unbemerkt bestehen bleiben, da
  Grenzwerte das Add-on ueberleben.

### Documentation
- README und CONFIGURATION.md: Betriebsart **Extern ueber Digital I/O** als
  Voraussetzung dokumentiert, mit Messwerten zu allen drei Modi und
  Erklaerung, warum Intern und Modbus TCP nicht funktionieren.

## [0.10.9] - 2026-08-15

### Fixed
- **Regelzyklus stuerzte ab, wenn der SOC-Sensor 'unavailable' meldet.**
  `float('unavailable')` wirft eine Exception, und das uebliche `or 0`
  faengt das nicht ab, weil nicht-leerer Text wahr ist. Im externen
  Modbus-Modus ist das gefaehrlich: ein ausgefallener Zyklus bedeutet
  einen ausbleibenden Schreibzugriff, und nach dem Timeout blockiert der
  Wechselrichter die Batterie. Der Zyklus verwendet jetzt den zuletzt
  bekannten SOC weiter.

### Added
- **Haltetest** (`POST /api/hold_test`, Knopf im Dashboard): schreibt einen
  deutlich abweichenden Wert (Default 2000 W) auf Register 1038 und
  beobachtet ihn 3 Minuten lang, ohne nachzuschreiben.
  - Der Registertest zeigt nur, ob ein Wert die naechste Sekunde
    ueberlebt. Entscheidend fuer eine Steuerung ist aber, ob er ueber
    Minuten haelt.
  - Wird er ueberschrieben, nennt der Test den Zeitpunkt - daraus ergibt
    sich, wie oft nachgeschrieben werden muesste.
  - Der Originalwert wird am Ende wiederhergestellt.

## [0.10.8] - 2026-08-15

### Added
- **Registertest** (`POST /api/register_test`, Knopf im Dashboard):
  schreibt je Limit-Register einen minimal veraenderten Testwert, liest
  zurueck und stellt den Originalwert sofort wieder her. Beantwortet die
  Frage, ob der Wechselrichter die Register tatsaechlich ANNIMMT -
  Lesbarkeit allein beweist das nicht.
  - Schreibt bewusst auch im Dry-Run, da genau das geprueft werden soll
  - Wird ausschliesslich manuell ausgeloest, mit Rueckfrage
  - Nennt den aktiven Batteriemanagement-Modus, weil das Verhalten davon
    abhaengen kann
- CONFIGURATION.md: Abschnitt zum Batteriemanagement-Modus (Register 1080)
  und warum die forecast-Strategie fuer Modus 0 entworfen ist

## [0.10.7] - 2026-08-15

### Fixed
- **Entladegrenze wurde unnoetig beschnitten.** Der Planer setzte
  `max_discharge_power` auf den Wert von `max_charge_power`, obwohl beides
  nichts miteinander zu tun hat. An realer Hardware bedeutete das z.B.
  4300 W statt der vom Wechselrichter erlaubten 4545 W.

### Added
- Neue Option `max_discharge_power` (Standard 0 = Limit des
  Wechselrichters uebernehmen, beim Start aus Register 1040 gelesen).
  Nur setzen, wenn das Entladen bewusst gedrosselt werden soll.

## [0.10.6] - 2026-08-15

### Added
- **Registerdiagnose beim Start** (auch im Dry-Run, da rein lesend):
  protokolliert Batteriekapazitaet (1068), Management-Modus (1080) und die
  vier Limit-Register. Damit laesst sich VOR dem Scharfschalten pruefen, ob
  die Steuerung am eigenen Geraet ueberhaupt funktionieren kann.
- Warnung, wenn die vom Wechselrichter gemeldete Kapazitaet deutlich von
  `battery_capacity` abweicht - alle Energieberechnungen haengen daran.

### Fixed
- Die Rueckmeldung aus den Registern wurde im Dry-Run gar nicht gelesen.
  Lesen ist gefahrlos; jetzt wird der Ist-Zustand auch dort geloggt und dem
  geplanten Zustand gegenuebergestellt.
- Abweichungspruefung deckt jetzt auch die beiden Leistungsregister ab
  (vorher nur min_soc/max_soc).

## [0.10.5] - 2026-08-15

### Fixed
- `update_charging_plan()` lief auch in der `forecast`-Strategie und fragte
  dort erfolglos die Tibber-Sensoren ab. Letzte verbliebene Quelle fuer
  404-Warnungen im Log ohne Tibber-Integration.

## [0.10.4] - 2026-08-15

### Fixed
- **Forecast.Solar Ratelimit nach Sekunden erschoepft (HTTP 429).** Der
  Planer fragte die Prognose an vier Stellen pro Zyklus ab (Nachtbedarf,
  Fehlbetrag morgen, Kalibrierung, Drosselung), jeweils mal Anzahl der
  Dachflaechen - rund 10 Abrufe alle 30 Sekunden bei einem Limit von 12
  pro Stunde.
  - Der Cache wurde nur bei Erfolg gesetzt; nach dem ersten 429 lief jeder
    Zyklus erneut ins Limit
  - Ein fehlendes Datum im Cache loeste einen kompletten Neuabruf aus
- Cache haelt jetzt die Rohdaten aller Tage aus **einem** Abruf und
  beantwortet daraus auch Anfragen fuer Tage ohne Daten
- Nach HTTP 429 wird bis zum von der API genannten `retry-at` pausiert,
  nach Netzwerkfehlern 10 Minuten

### Changed
- Cache-Dauer von 15 auf 30 Minuten erhoeht (2 Abrufe/Stunde)
- Ebenen mit identischer Neigung UND Ausrichtung werden zu einer
  zusammengefasst. Gleiche Geometrie ergibt dieselbe Tageskurve, nur
  skaliert - die Summe der kWp ist exakt aequivalent und halbiert die
  Abrufe. Unterschiedliche Geometrie bleibt getrennt.

### Documentation
- CONFIGURATION.md: Ratelimit, Cache-Verhalten und die Log-Meldung bei
  Ueberschreitung dokumentiert

## [0.10.3] - 2026-08-15

### Documentation
- README und CONFIGURATION.md um die Forecast.Solar-Einrichtung ergaenzt:
  keyless API-Nutzung, warum der sensorbasierte Fallback mit neueren
  Versionen der HA-Integration nicht mehr funktioniert, und dass ohne
  stuendliche Prognose die gesamte Strategie wirkungslos bleibt
- Neuer "Schritt 0" in der Inbetriebnahme, vor dem Dry-Run
- Kommentar direkt an der Option in config.yaml

## [0.10.2] - 2026-08-15

### Fixed
- **Forecast.Solar API lieferte nie Daten.** Zwei Fehler zusammen:
  - Der Parser erwartete `result.watt_hours`; die API liefert `result`
    als flaches `{Zeitstempel: Wh}`
  - Verwendet wurde `estimate/watthours` (ueber den Tag KUMULIERT) statt
    `estimate/watthours/period` (Werte pro Stunde)
- **Prognose fuer morgen war die von heute.** `get_hourly_forecast()`
  ignorierte das Zieldatum, der PV-Shaping-Planer bekam fuer "morgen" die
  heutige Kurve - der dynamische SOC-Deckel rechnete damit falsch.
- Der Cache wurde nach dem Abruf ueberschrieben und verlor die
  Tagesaufteilung, wodurch jede Abfrage fuer morgen einen neuen API-Call
  ausgeloest haette.

### Changed
- **API-Key ist jetzt optional.** Ohne Key wird die oeffentliche
  Schnittstelle genutzt (Key-Segment entfaellt in der URL). Damit ist die
  Stundenprognose ohne Registrierung verfuegbar; ein Abruf deckt heute und
  morgen ab und bleibt im Ratelimit.

## [0.10.1] - 2026-08-15

### Fixed
- **Log-Flut bei fehlenden Tibber-Sensoren**: `/api/status` fragte die
  Tibber-Sensoren bei jedem Aufruf ab, auch in der `forecast`-Strategie.
  Ohne Tibber-Integration ergab das drei 404-Requests gegen Home Assistant
  alle zwei Sekunden. Die Abfragen entfallen jetzt ausserhalb der
  Preisstrategie.
- `/api/battery_schedule` und `/api/tibber_price_chart` berechneten auch in
  der `forecast`-Strategie preisbasierte "Ladefenster" und liefen bei
  fehlenden Tibber-Sensoren auf HTTP 500. Beide melden dort jetzt
  `not_applicable_in_forecast_strategy`.

## [0.10.0] - 2026-08-15

### Fixed
- **Ladestrategie `forecast` war nie aktiv** - `charging_strategy` und alle Korridor-Parameter
  standen faelschlich im `schema:`-Block statt in `options:`
  - `charging_strategy: forecast` wurde von Home Assistant als (ungueltiger) Schema-Typ gelesen
  - Dadurch erreichte die Option nie `/data/options.json`, und `app.py` fiel auf den
    Default `'price'` zurueck - die Forecast-Logik lief nie
  - Parameter jetzt korrekt in `options:` mit passenden Schema-Typen in `schema:`

### Changed
- Standard-Ladestrategie ist jetzt `forecast` (vorher effektiv `price`)

### Added
- **PV-Shaping-Planer** (`core/pv_shaping_planner.py`) - prognosebasierte
  Batteriesteuerung OHNE Netzladung, Ziel ist Batterielebensdauer
  - Dynamischer SOC-Deckel: weniger Verweilzeit bei hohem SOC
  - Ladeleistungs-Drosselung: verteilt die Ladung ueber die PV-Stunden,
    senkt die C-Rate und verschiebt das Erreichen des Ziel-SOC nach hinten
  - Entladegrenze schuetzt vor Tiefentladung
  - Periodische Kalibrierladung auf 100% fuer die BMS-SOC-Schaetzung,
    nur an Tagen mit ausreichender PV-Prognose
- **Dry-Run-Modus** (`dry_run: true`, Default) - Entscheidungen werden nur
  geloggt, es wird NICHTS auf den Wechselrichter geschrieben
- **Limit-Register** (Kostal Modbus-Doku Kap. 3.4): 1038 max. Ladeleistung,
  1040 max. Entladeleistung, 1042 Minimum SOC, 1044 Maximum SOC
- **Byte-Order-Pruefung** (Register 5) beim Start - der Wechselrichter kann
  auf Big-endian (ABCD/SunSpec) stehen, dann waeren alle Float-Werte falsch
- Periodisches Neuschreiben der Limits (10 min), falls sie einen Reset des
  Wechselrichters nicht ueberleben

### Fixed
- **Register 1068 war als "Battery SOC" beschriftet** - laut Kostal-Doku ist
  es die Batteriekapazitaet in Wh. Betraf `test_connection()` und die README.

- **Nachtsperre**: Ausserhalb der PV-Stunden wird das Ladelimit auf 0 W gesetzt.
  Ladung koennte dort nur aus dem Netz kommen.
- **Dashboard-Karte "Batterieschonung"** zeigt den aktuellen Plan, die Begruendung
  und die aus den Registern zurueckgelesenen Werte. Preisbasierte Karten werden
  in der `forecast`-Strategie ausgeblendet.

### Removed
- **`manual_load_profile`** entfernt. Ein handgeschriebenes Lastprofil konkurrierte
  mit den echten Messwerten des Verbrauchslerners. Zum Beschleunigen der Anlaufphase
  stattdessen den CSV-/HA-Import nutzen. (Die Option hatte ausserdem keinen
  Schema-Eintrag und haette die HA-Konfigurationspruefung scheitern lassen.)

### Deprecated
- `core/forecast_optimizer.py` ("Evening Top-up") nicht mehr verdrahtet: die
  abendliche Nachladung via Register 1034 zog Energie zwangsweise aus dem
  Netz. Ersetzt durch den PV-Shaping-Planer.

## [0.9.6] - 2025-11-05

### Fixed
- **BREAKING: Repository Structure** - Korrekte Home Assistant Add-on Repository Struktur
  - Add-on Dateien in Unterverzeichnis `kostal_battery_manager/` verschoben
  - `repository.yaml` im Root erstellt (ERFORDERLICH für alle Add-on Repositories!)
  - Struktur entspricht jetzt den offiziellen Home Assistant Standards
  - **Migration**: Repository in Home Assistant entfernen und neu hinzufügen

### Technical
- Alle Add-on Dateien (config.yaml, Dockerfile, etc.) jetzt in `kostal_battery_manager/` Verzeichnis
- `repository.yaml` definiert das Repository auf oberster Ebene
- Ordnerstruktur: Root → repository.yaml + kostal_battery_manager/ → Add-on Dateien

## [0.9.5] - 2025-11-05

### Fixed
- **Home Assistant Repository Detection** - Versuch, Repository-Erkennung zu fixen (FEHLGESCHLAGEN)
  - `repository.yaml` entfernt - das war ein Fehler
  - Diese Version funktioniert NICHT korrekt

## [0.6.4] - 2025-11-04

### Changed
- **📊 Verbesserte Grafiken** - Optimierte Darstellung nach Benutzerwunsch
- **Tibber Preise als Balkendiagramm** - Besser erkennbare Preisunterschiede
  - Aktuelle Stunde rot hervorgehoben
  - Alle anderen Balken in Gelb
- **Verbrauchsdiagramm mit zwei Linien**:
  - **Gelbe gefüllte Linie**: Prognostizierter Verbrauch (basierend auf gelernten Daten)
  - **Blaue Linie**: Tatsächlicher Verbrauch heute (Live-Daten aus Home Assistant)
  - Beide Linien im gleichen Diagramm für direkten Vergleich
- **Tatsächlicher Verbrauch heute** wird automatisch aus Home Assistant abgerufen
  - Nutzt `home_consumption_sensor` Konfiguration
  - Zeigt nur bereits vergangene Stunden
  - Automatische Watt→kW Konvertierung
  - Aktualisierung alle 5 Minuten

### Technical
- API-Endpunkt `/api/consumption_forecast_chart` erweitert
  - Liefert jetzt sowohl `forecast` als auch `actual` Daten
  - Ruft History-Daten für heute ab
  - Gruppiert nach Stunden und berechnet Durchschnitte
- Chart-Typ für Preise von `line` zu `bar` geändert
- Chart-Typ für Verbrauch von `bar` zu `line` mit zwei Datasets geändert
- `spanGaps: true` für tatsächlichen Verbrauch (verbindet Linie auch bei fehlenden Stunden)

### Why This Matters
- **Besserer Vergleich** - Prognose vs. Realität direkt sichtbar
- **Genauere Planung** - Sehe wie genau deine Prognosen sind
- **Optimierung möglich** - Erkenne Abweichungen und passe dein Verhalten an
- **Live-Feedback** - Aktueller Verbrauch zeigt wie der Tag verläuft

### Example
Verbrauchsdiagramm zeigt:
- 06:00 Uhr: Prognose 2.0 kW (gelb), Tatsächlich 1.8 kW (blau) → Unter Prognose!
- 12:00 Uhr: Prognose 1.2 kW (gelb), Tatsächlich 1.5 kW (blau) → Über Prognose!
- 18:00 Uhr: Prognose 2.0 kW (gelb), noch keine Daten (blau nicht sichtbar)

→ Du siehst sofort ob du mehr oder weniger verbrauchst als erwartet!

## [0.6.3] - 2025-11-04

### Added
- **📊 Grafische Darstellungen im Dashboard** - Zwei neue interaktive Charts
- **Tibber Preisverlauf-Grafik** - Zeigt stündliche Strompreise für heute
  - Liniendiagramm mit allen 24 Stunden
  - Aktuelle Stunde hervorgehoben (roter Punkt)
  - Preise in Cent/kWh dargestellt
  - Automatische Aktualisierung alle 5 Minuten
- **Verbrauchsprognose-Grafik** - Zeigt prognostizierten Verbrauch basierend auf historischen Daten
  - Balkendiagramm mit stündlichen Verbrauchswerten
  - Aktuelle Stunde hervorgehoben (gelb)
  - Verbrauch in kW dargestellt
  - Basiert auf den gelernten Verbrauchsmustern
- **Chart.js Integration** - Moderne, responsive Diagramme
- Neue API-Endpunkte:
  - `GET /api/tibber_price_chart` - Preisverlauf für Grafik
  - `GET /api/consumption_forecast_chart` - Verbrauchsprognose für Grafik

### Technical
- Chart.js 4.4.0 von CDN eingebunden
- Responsive Charts mit Dark-Mode-Support
- Automatische Aktualisierung der Grafiken alle 5 Minuten
- Highlighting der aktuellen Stunde in beiden Grafiken
- Optimierte Chart-Performance mit `maintainAspectRatio: false`

### Why This Matters
- **Visuelle Übersicht** - Schnell erkennbare Muster im Preisverlauf
- **Bessere Planung** - Sehe wann die Preise steigen/fallen
- **Verbrauchseinblick** - Verstehe deine Verbrauchsmuster über den Tag
- **Datenbasierte Entscheidungen** - Kombiniere Preis + Verbrauch für optimale Ladezeiten

### Example
Preisgrafik zeigt:
- 00:00-06:00: Niedrige Preise (grün) → Optimal zum Laden
- 06:00-20:00: Hohe Preise (gelb/rot) → Batterie nutzen
- 20:00-24:00: Mittlere Preise

Verbrauchsgrafik zeigt:
- Morgens 06:00-08:00: Hoher Verbrauch (Frühstück, Kaffee)
- Mittags 12:00-14:00: Mittlerer Verbrauch (Kochen)
- Abends 17:00-21:00: Hoher Verbrauch (Abendessen, TV)

→ Kombiniert: Batterie vorher laden wenn Preise niedrig sind!

## [0.6.2] - 2025-11-04

### Fixed
- **🔧 UI Display Fix** - "undefined Tage importiert" zeigt jetzt die korrekte Anzahl
- Import-Response enthält jetzt `imported_days` Feld in allen Funktionen
- CSV-Import und HA-Import zeigen beide die importierten Tage korrekt an
- Alle Error-Responses enthalten jetzt konsistent alle Felder

### Technical
- `import_from_home_assistant()` fügt `imported_days` zur Response hinzu
- `import_from_csv()` fügt `imported_days` zur Response hinzu
- Alle Error-Responses enthalten: `imported_hours`, `imported_days`, `skipped_days`
- Konsistente Response-Struktur für bessere UI-Integration

## [0.6.1] - 2025-11-04

### Fixed
- **🔧 Watt-Sensor Unterstützung** - Automatische Umrechnung von Watt zu kW
- Sensoren die Leistung in Watt (W) statt kWh liefern werden nun korrekt verarbeitet
- Werte > 50 werden automatisch als Watt erkannt und durch 1000 geteilt (W → kW)
- Filter-Schwelle von 50 kWh auf 50.000 W (50 kW) erhöht für realistische Hausverbräuche
- Mindest-Daten-Schwelle von 12 auf 3 Stunden pro Tag reduziert (für spärliche History-Daten)
- Detailliertes Logging: Zeigt genau welche Einträge warum gefiltert wurden
- Zeigt verfügbare Stunden pro Tag für besseres Debugging

### Technical
- Automatische Einheit-Erkennung: Werte > 50 = Watt, Werte ≤ 50 = kWh
- Neue Logging-Counter: skipped_unavailable, skipped_not_numeric, skipped_negative, skipped_too_high
- Log zeigt jetzt für jeden Tag: Anzahl Stunden und welche Stunden vorhanden sind
- Beispiel: 865 W → 0.865 kW automatisch konvertiert

### Why This Matters
- **Funktioniert mit Standard-Sensoren** - Die meisten HA Verbrauchssensoren liefern Watt, nicht kWh
- **Bessere Datennutzung** - 3 Stunden pro Tag reichen jetzt (vorher 12), mehr Tage werden importiert
- **Besseres Debugging** - Klare Logs zeigen genau, was mit den Daten passiert

## [0.6.0] - 2025-11-04

### Added
- **🏠 Automatischer Home Assistant History Import** - Importiere Verbrauchsdaten direkt aus Home Assistant
- Neuer Button "Aus Home Assistant importieren" auf Import-Seite
- Automatische Datenverarbeitung der letzten 28 Tage aus dem konfigurierten Sensor
- Intelligente Handhabung hochauflösender Daten (mehrere Werte pro Stunde werden gemittelt)
- Ältere Daten (nur stündlich) werden direkt übernommen
- Neue API-Endpunkte:
  - `POST /api/consumption_import_ha` - Import aus Home Assistant History
- Erweiterte HA Client-Funktionen:
  - `get_history()` - Abrufen historischer Daten über HA REST API
- Erweiterte ConsumptionLearner-Funktionen:
  - `import_from_home_assistant()` - Vollautomatischer Import mit Datenverarbeitung

### Technical
- Nutzt Home Assistant History API (`/api/history/period/{start_time}`)
- Gruppiert Datenpunkte nach (Datum, Stunde) und berechnet Durchschnitt
- Filtert negative Werte und unrealistische Werte (> 50 kWh)
- Überspringt Tage mit weniger als 12 Stunden Daten
- Füllt fehlende Stunden innerhalb eines Tages mit Tagesdurchschnitt
- Löscht alte manuelle Daten vor neuem Import (verhindert Datenkonflikte)
- Konfigurierbar über `home_consumption_sensor` in config.yaml

### Why This Matters
- **Kein manueller CSV-Export mehr nötig** - Direkter Zugriff auf HA-Verlaufsdaten
- **Hochauflösende Daten optimal genutzt** - Mehrfachwerte pro Stunde → präziser Durchschnitt
- **Robuste Datenverarbeitung** - Filtert Ausreißer, Fehler und unrealistische Werte
- **Ein-Klick-Import** - 28 Tage Historie mit einem Klick importiert
- **Intelligente Lückenbehandlung** - Fehlende Stunden werden mit Tagesdurchschnitt gefüllt

### Example
Statt CSV manuell erstellen:
```
1. Daten aus HA exportieren
2. CSV formatieren
3. Hochladen
```

Jetzt:
```
1. Button klicken
2. Fertig!
```

Sensor `sensor.ksem_home_consumption` liefert:
- Montag 7:00-8:00: [2.1, 2.3, 2.0, 2.4, ...] (300 Werte) → Ø 2.2 kWh
- Dienstag 7:00-8:00: [1.9] (1 Wert) → 1.9 kWh
→ System verarbeitet beide Fälle korrekt!

## [0.5.9] - 2025-11-04

### Fixed
- **🗑️ CSV-Import löscht alte Daten** - Verhindert, dass alte manuelle Daten erhalten bleiben
- Neue Funktionen: `clear_all_manual_data()` und `clear_all_data()`
- Vor jedem CSV-Import werden alte manuelle Daten automatisch gelöscht
- Behebt Problem: CSV ohne 7.10. hochladen zeigt trotzdem den 7.10.

### Added
- **🔍 HTML Debug-Seite** - `/debug_consumption` zeigt Daten als lesbare Tabelle
- Zeigt für jedes Datum: Anzahl Stunden, erste/letzte Stunde, manuell/gelernt
- Total-Übersicht: Alle Stunden (manuell + automatisch gelernt)
- Einfacher Link statt JSON-API

### Technical
- `consumption_learner.clear_all_manual_data()` - Löscht nur manuelle Daten
- `consumption_learner.clear_all_data()` - Löscht ALLE Daten
- CSV-Import ruft automatisch `clear_all_manual_data()` auf

## [0.5.8] - 2025-11-04

### Added
- **🔍 Debug-Endpoint** - `/api/debug_consumption/<date>` für Import-Debugging
- Zeigt Rohdaten aus der Datenbank für ein bestimmtes Datum
- Hilft bei der Diagnose von Import-Problemen

### Technical
- Endpoint zeigt timestamp, hour, consumption_kwh, is_manual, created_at
- Beispiel: `/api/debug_consumption/2025-10-07`

## [0.5.7] - 2025-11-04

### Fixed
- **🔧 API-Routen im JavaScript** - Verwenden dynamischen basePath statt url_for()
- JavaScript ermittelt basePath aus aktueller URL
- Alle fetch() Aufrufe nutzen `basePath + '/api/...'`
- Behebt JSON.parse Fehler beim Laden der Import-Seite
- API-Calls funktionieren korrekt mit /ingress Routing

### Technical
- basePath = `window.location.pathname.replace(/\/[^\/]*$/, '')`
- Von `/ingress/consumption_import` → basePath = `/ingress`
- fetch: `basePath + '/api/consumption_data'` → `/ingress/api/consumption_data`

## [0.5.6] - 2025-11-04

### Fixed
- **🔗 Relative Links für /ingress Routing** - Links verwenden nun relative Pfade
- Import-Link im Dashboard: `consumption_import` statt `{{ url_for(...) }}`
- Zurück-Link: `./` statt `{{ url_for('dashboard') }}`
- Behebt 404-Fehler durch fehlenden `/ingress` Präfix in generierten URLs
- Funktioniert korrekt mit HA Ingress unter `/addon_slug/ingress/` Pfad

### Technical
- Relative Links funktionieren unabhängig vom Ingress-Pfad
- Dashboard: `/ingress` → Link: `consumption_import` → Ziel: `/ingress/consumption_import`
- Import: `/ingress/consumption_import` → Link: `./` → Ziel: `/ingress`

## [0.5.5] - 2025-11-04

### Fixed
- **🎨 Template-Struktur korrigiert** - consumption_import.html verwendet jetzt base.html
- Extends base.html wie alle anderen Seiten (dashboard, logs, etc.)
- Konsistente Template-Struktur für korrektes Rendering im HA Ingress
- Behebt Problem mit HA-Frontend-Overlay das die Seite überdeckte
- Route nutzt wieder render_template() statt direktes File-Reading

### Technical
- Template-Struktur: `{% extends "base.html" %}` + `{% block content %}`
- Inline-Styles im content-Block für Import-spezifisches Styling
- Verwendet url_for() für alle API-Routen und Links
- Funktioniert nun konsistent mit HA Ingress-Architektur

## [0.5.4] - 2025-11-04

### Fixed
- **📄 Direktes HTML-Serving** - consumption_import.html wird nun direkt gelesen und gesendet
- Umgehung von render_template() für standalone HTML-Datei
- Vermeidet potenzielle Jinja2-Rendering-Probleme
- Explizite UTF-8 Encoding beim Lesen der Datei
- Fehlerbehandlung mit aussagekräftigen Fehlermeldungen

### Technical
- Route liest HTML-Datei direkt mit open() und return f.read()
- Try-catch Block für besseres Error-Handling
- Loggt Fehler für einfacheres Debugging

## [0.5.3] - 2025-11-04

### Fixed
- **🔧 ProxyFix für url_for() Ingress-Support** - Werkzeug ProxyFix Middleware hinzugefügt
- Flask app.wsgi_app mit ProxyFix konfiguriert für korrekte URL-Generierung
- url_for() generiert nun URLs mit korrektem Ingress-Präfix
- Verarbeitet X-Forwarded-* Header von Home Assistant Ingress-Proxy
- Dashboard Import-Link zeigt nun korrekte URL beim Mouseover

### Technical
- Importiert werkzeug.middleware.proxy_fix.ProxyFix
- Konfiguration: x_for=1, x_proto=1, x_host=1, x_prefix=1
- Ermöglicht Flask, hinter Reverse-Proxy korrekt zu arbeiten

## [0.5.2] - 2025-11-04

### Fixed
- **🔗 Dashboard Import-Link** - Verwendung von url_for() für korrektes Ingress-Routing
- Import-Link im Dashboard verwendet nun Flask url_for('consumption_import_page')
- Statt hardcodiertem '/consumption_import' nun dynamische URL-Generierung
- Gewährleistet korrektes Routing durch Home Assistant Ingress-Proxy

### Technical
- Änderung in dashboard.html: href="{{ url_for('consumption_import_page') }}"
- Funktioniert mit allen Ingress-URL-Präfixen

## [0.5.1] - 2025-11-04

### Fixed
- **🔧 Ingress-Kompatibilität für Import-Seite** - Konvertierung zu Standalone-HTML
- Entfernung von Jinja2-Template-Vererbung ({% extends %}, {% block %})
- Alle CSS-Styles inline in `<head>` eingebettet
- JavaScript inline integriert zur Vermeidung von Static-File-Problemen
- Behebt weißen Bildschirm bei Zugriff über Home Assistant Ingress
- Relative Pfade für "Zurück zum Dashboard" Link

### Technical
- Template consumption_import.html vollständig eigenständig
- Keine Abhängigkeiten von base.html oder static files
- Funktioniert korrekt mit HA Ingress URL-Präfix

## [0.5.0] - 2025-11-04

### Added
- **📊 CSV-Import für detaillierte Verbrauchsdaten** - Importiere 28 Tage mit individuellen Tagesprofilen
- **✏️ Web-basierter Tabellen-Editor** - Bearbeite Verbrauchsdaten direkt im Browser
- Neue Import-Seite `/consumption_import` mit vollem Import/Editor Interface
- CSV-Import unterstützt:
  - Detaillierte historische Daten (28 Tage × 24 Stunden = 672 Datenpunkte)
  - Deutsches Zahlenformat (Komma als Dezimaltrennzeichen)
  - Flexible Datumsformate (YYYY-MM-DD oder DD.MM.YYYY)
  - Automatische Wochentagserkennung aus Datum
  - Echtzeit-Validierung und Fehlerbehandlung
- CSV-Vorlagen-Download-Funktion für einfachen Einstieg
- Web-Editor Features:
  - 28×24 Daten-Matrix mit vollständiger Bearbeitung
  - Zeilen hinzufügen/löschen
  - Automatische Wochentagsberechnung
  - Laden vorhandener Daten aus Datenbank
  - Speichern bearbeiteter Daten
- Dashboard-Link zur Import-Seite
- Neue API-Endpunkte:
  - `POST /api/consumption_import_csv` - CSV-Datei Upload
  - `GET /api/consumption_data` - Vorhandene Daten laden
  - `POST /api/consumption_data` - Bearbeitete Daten speichern
- Erweiterte ConsumptionLearner-Funktionen:
  - `import_detailed_history()` - Import mit individuellen Tagesprofilen
  - `import_from_csv()` - Robustes CSV-Parsing mit Fehlerbehandlung

### Changed
- Verbrauchslernen unterscheidet jetzt zwischen Wochentagen und Wochenende
- Detailliertere Datenbasis ermöglicht präzisere Vorhersagen
- Verbesserte Validierung für negative und unrealistische Werte

### Technical
- CSV-Parser mit `io.StringIO` und `csv.DictReader`
- Unterstützung für beide Dezimaltrennzeichen (Komma/Punkt)
- Flexible Datumsformatierung mit Fallback
- Vollständige Fehlerbehandlung mit detaillierten Log-Meldungen
- `is_manual` Flag zur Unterscheidung manueller vs. gelernter Daten
- Automatische Bereinigung alter Daten über Lernzeitraum

### Why This Matters
- **Wochenend-Muster**: Samstag/Sonntag haben oft andere Verbrauchsmuster als Wochentage
- **Präzisere Vorhersagen**: 28 individuelle Tagesprofile statt 1 generisches Profil
- **Schneller Start**: Mit vorhandenen Daten sofort optimale Ladeentscheidungen
- **Flexibilität**: CSV-Import für Masse, Web-Editor für Feintuning

### Example
Statt ein generisches Tagesprofil für alle 28 Tage:
```
Jeden Tag: 7-8 Uhr = 2.0 kWh
```

Jetzt individuelle Profile pro Wochentag:
```
Montag 7-8 Uhr: 2.5 kWh (Arbeitstag, Homeoffice)
Samstag 7-8 Uhr: 0.8 kWh (Wochenende, länger geschlafen)
```
→ Bessere Vorhersagen, präzisere Ladesteuerung!

## [0.4.0] - 2025-11-04

### Added
- **🎓 Consumption Learning System** - Self-learning household consumption patterns
- SQLite-based consumption learning with 4-week rolling window (configurable 7-90 days)
- Manual load profile initialization for immediate baseline (24-hour profile)
- Automatic hourly consumption recording from Home Assistant sensor
- Intelligent energy deficit prediction based on learned consumption patterns
- Consumption-aware charging optimization (replaces simple PV threshold)
- New dashboard card "Verbrauchslernen" showing:
  - Learning progress percentage (manual vs. learned data)
  - Total data records and learned hours
  - Time period of collected data
- New API endpoint `/api/consumption_learning` for statistics and hourly profile
- Configuration parameters:
  - `enable_consumption_learning`: Enable/disable learning (default: true)
  - `learning_period_days`: Learning period in days (default: 28, range: 7-90)
  - `home_consumption_sensor`: HA sensor for consumption recording
  - `manual_load_profile`: Initial 24-hour baseline profile (0-23 hours with kW values)
  - `average_daily_consumption`: Alternative - daily consumption in kWh (divided by 24 for fallback)
  - `default_hourly_consumption_fallback`: Fallback value when no data (default: 1.0 kWh/h)

### Changed
- **Improved charging logic** now considers hourly consumption patterns vs. hourly PV forecast
- Simple daily PV threshold replaced with sophisticated hourly energy balance calculation
- TibberOptimizer now uses `predict_energy_deficit()` method for better decisions
- Charging decisions now account for morning consumption peaks even when daily PV total is sufficient
- Status explanations updated to show energy balance information
- ConsumptionLearner integrated into TibberOptimizer for real-time predictions
- **Flexible fallback configuration**: Choose between manual 24h profile OR simple daily average
  - Priority: 1) `default_hourly_consumption_fallback`, 2) `average_daily_consumption / 24`, 3) 1.0 kWh/h
  - No error if no baseline data provided - system starts learning from zero with sensible fallback

### Technical
- Created `ConsumptionLearner` class with SQLite backend (`/data/consumption_learning.db`)
- Database schema with `hourly_consumption` table tracking manual/learned data
- `add_manual_profile()` generates 28 days of baseline from user's 24-hour profile
- `record_consumption()` replaces old data automatically (rolling window)
- `get_average_consumption()` returns learned average per hour
- `predict_consumption_until()` predicts total consumption to target hour
- `get_statistics()` provides learning progress metrics
- Automatic cleanup of data older than learning period
- Hourly consumption recording in controller loop
- Dashboard auto-updates learning statistics every 30 seconds

### Why This Matters
The simple "daily PV threshold" (e.g., 16.9 kWh PV forecast) doesn't account for time distribution:
- **Problem**: Morning 7-10am has only 1.07 kWh PV but 3-5 kWh consumption → Battery depletes!
- **Solution**: Learning system analyzes hourly patterns and charges battery to bridge morning gap

### Example
Before (v0.3.x):
- Daily PV: 16.9 kWh > 5 kWh threshold → ✅ Don't charge
- Reality: Morning deficit drains battery → ❌ Problem!

After (v0.4.0):
- Hourly analysis: PV 7-10am = 1.07 kWh, Consumption 7-10am = 4.5 kWh
- Predicted deficit: 3.43 kWh → 🔋 Charge battery during night!
- Result: Battery ready for morning consumption peak → ✅ Success!

## [0.3.7] - 2025-11-03

### Fixed
- Improved condition labels to be more positive and intuitive
- "SOC unter Sicherheitsminimum" → "Sicherheits-SOC nicht unterschritten" (when OK)
- "Batterie bereits voll" → "Lade-Limit nicht erreicht/erreicht"
- Added actual values to all condition labels for better transparency
- Fixed logic error where 10% was shown as "< 10%"

### Changed
- Removed redundant "Geplante Ladezeit erreicht" condition
- Conditions now use: ✅ = Normal/OK, ❌ = Problem/Action needed
- All labels now show actual values in comparison (e.g., "17% ≥ 10%")

### Examples
Before:
- ❌ SOC unter Sicherheitsminimum (10% < 10%) ← Wrong!
- ❌ Batterie bereits voll (10% ≥ 100%) ← Confusing!
- ❌ Geplante Ladezeit erreicht ← Redundant

After:
- ✅ Sicherheits-SOC nicht unterschritten (17% ≥ 10%) ← Clear!
- ✅ Lade-Limit nicht erreicht (45% < 95%) ← Better!
- ✅ PV-Ertrag ausreichend (12.0 kWh > 5.0 kWh) ← Informative!

## [0.3.6] - 2025-11-03

### Added
- **Dynamic charging status explanation** on dashboard showing WHY and WHEN battery will be charged
- New "Ladestatus" card with human-readable explanation
- Visual condition checkboxes with green checkmarks (✅) and red crosses (❌)
- Shows all relevant conditions:
  - SOC below safety minimum
  - Battery already full
  - Sufficient PV expected
  - Planned charging time reached
  - Charging plan available
- Auto-updates every 5 seconds for real-time status
- New API endpoint `/api/charging_status` for detailed charging decision logic

### Examples
Status texts dynamically generated:
- "⚡ Der Speicher wird SOFORT geladen, weil der SOC (15%) unter dem Sicherheitsminimum von 20% liegt."
- "⏳ Der Speicher wird ab 01:34 Uhr geladen, sodass er bis 04:00 Uhr bei 95% ist."
- "☀️ Der Speicher wird nicht aus dem Netz geladen, weil der prognostizierte Solarertrag mit 12 kWh über dem Schwellwert von 5 kWh liegt."
- "✅ Der Speicher wird nicht geladen, weil er bereits bei 96% liegt (Ziel: 95%)."

### Technical
- Added `get_charging_status_explanation()` function for status generation
- Condition evaluation with priority system
- Integrated with existing charging decision logic

## [0.3.5] - 2025-11-03

### Added
- Comprehensive CONFIGURATION.md documentation explaining all parameters
- Detailed inline comments for all automation parameters
- Better explanation of `auto_charge_below_soc` (means "charge UP TO this SOC", not "charge only when below")

### Changed
- `battery_soc_sensor` is now visible and required in configuration (was hidden/optional before)
- Improved parameter descriptions with German explanations
- Added section headers in config.yaml for better organization

### Documentation
- Created detailed CONFIGURATION.md with:
  - Explanation of all SOC parameters and their meaning
  - Tibber smart charging parameter details
  - Example scenarios and calculations
  - Troubleshooting common issues
- Clarified that `auto_charge_below_soc` is the TARGET SOC (charge UP TO), not a condition
- Explained `auto_safety_soc` as immediate charging trigger (charge WHEN BELOW)

## [0.3.4] - 2025-11-03

### Fixed
- Removed redundant `min_soc` and `max_soc` parameters that were conflicting with existing parameters
- Now consistently uses `auto_safety_soc` as safety minimum (default 20%)
- Now consistently uses `auto_charge_below_soc` as target SOC (default 95%)

### Removed
- Config parameters `min_soc` and `max_soc` (use existing `auto_safety_soc` and `auto_charge_below_soc` instead)

### Changed
- Charging plan calculation and controller now use the same SOC parameters as other automation logic
- Better consistency across the entire application

## [0.3.3] - 2025-11-03

### Fixed
- **Critical:** Fixed timezone comparison error preventing charging plan calculation
- Changed `datetime.now()` to `datetime.now().astimezone()` for timezone-aware comparisons
- Resolved "can't compare offset-naive and offset-aware datetimes" error
- Charging plan calculation now works correctly with Tibber price data

### Technical
- All datetime comparisons in TibberOptimizer are now timezone-aware
- Properly handles timezone information from Tibber sensor data (UTC/ISO format)

## [0.3.2] - 2025-11-03

### Fixed
- Significantly improved logging for charging plan calculation to identify issues
- Added detailed error messages when calculation fails
- Now logs each step: checking prerequisites, fetching price data, analyzing prices
- Marks `last_calculated` even when no optimal plan is found

### Added
- Manual "Neu berechnen" button in charging plan card for testing
- New API endpoint `/api/recalculate_plan` to manually trigger calculation
- Better visibility of why charging plan calculation succeeds or fails

### Improved
- Logging now shows: number of prices (today/tomorrow), sensor names, missing data
- Error messages appear in system logs AND in dashboard logs
- Helps diagnose issues with Tibber sensor or missing price data

## [0.3.1] - 2025-11-03

### Changed
- Charging plan calculation now runs immediately on startup (not after 5 minutes)
- Improved documentation for `input_datetime` helpers in config.yaml

### Documentation
- Added detailed explanation of optional Home Assistant `input_datetime` integration
- Explained that input_datetime helpers must be created manually in HA configuration.yaml
- Added example YAML configuration for creating the helpers
- Clarified that input_datetime integration is optional and addon works without it

## [0.3.0] - 2025-11-03

### Added
- **Intelligent Tibber-based charging optimization** - Advanced price analysis for optimal charging
- Automatic detection of price increase point (end of cheap period)
- Backward calculation of optimal charging start time based on battery SOC
- Charging plan display in dashboard showing planned start/end times and last calculation
- New `TibberOptimizer` core module for smart charging logic
- Support for configurable price thresholds:
  - `tibber_price_threshold_1h`: Price increase threshold vs previous hour (default 8%)
  - `tibber_price_threshold_3h`: 3-hour block comparison threshold (default 8%)
  - `charge_duration_per_10_percent`: Charging time per 10% SOC (default 18 minutes)
  - `min_soc`: Minimum safety SOC (default 20%)
  - `max_soc`: Maximum target SOC (default 95%)
- Optional Home Assistant input_datetime integration for charging plan visualization
- New API endpoint `/api/charging_plan` for charging schedule information
- Periodic charging plan updates (every 5 minutes)

### Changed
- Auto-optimization mode now uses sophisticated price trend analysis instead of simple price levels
- Controller considers both price trends (1h and 3h windows) and PV forecast
- Charging starts automatically at calculated optimal time
- Charging stops when price increases or battery reaches max SOC
- Enhanced `/api/status` endpoint now includes charging plan information

### Technical
- Ported Home Assistant automation logic to Python for standalone operation
- Added charging plan calculation with timezone-aware datetime handling
- Integration with Home Assistant `input_datetime` helpers (optional)
- Improved error handling for missing/invalid price data
- Fallback behavior when no optimal charging time is found
- Comprehensive logging for all charging decisions
- Manual charging control remains fully functional alongside automatic optimization

## [0.2.7] - 2025-11-03

### Fixed
- Dashboard now displays correct SOC parameters (`auto_safety_soc` and `auto_charge_below_soc` instead of removed `min_soc`/`max_soc`)
- Updated labels: "Sicherheits-SOC" and "Lade-Limit" for better clarity

## [0.2.6] - 2025-11-03

### Changed
- Removed duplicate SOC parameters `min_soc` and `max_soc` (now only using `auto_safety_soc` and `auto_charge_below_soc` for clarity)
- Renamed "Modus" to "Status" in status overview with German labels:
  - "Standby" (statt "automatic")
  - "Lädt (manuell)" (statt "manual_charging")
  - "Lädt (Auto)" (statt "auto_charging")
- Removed redundant "Steuerung" display from status overview

### Removed
- Config parameters `min_soc` and `max_soc` (replaced by clearer `auto_safety_soc` and `auto_charge_below_soc`)

## [0.2.5] - 2025-11-03

### Added
- Automation status display in status overview
- Toggle switch for automation (replaces button)
- Configurable automation parameters:
  - `auto_pv_threshold`: PV forecast threshold (default 5.0 kWh)
  - `auto_charge_below_soc`: Maximum SOC for charging (default 95%)
  - `auto_safety_soc`: Safety minimum SOC (default 20%)
- New API endpoint: `/api/control` with `toggle_automation` action

### Changed
- Automation is now ON by default on startup
- Controller logic uses configurable parameters instead of hardcoded values
- Improved automation status visibility with toggle switch and status indicator
- Button replaced with professional toggle switch for better UX

### UI
- Real-time automation status display (AN/AUS with colored dot)
- Toggle switch shows current state and allows easy on/off control
- Automation parameters now configurable in addon configuration

## [0.2.4] - 2025-11-03

### Fixed
- Charging power slider value now correctly applied when starting charge
- Previously always used max_charge_power, now uses slider value
- Dark mode text visibility significantly improved with white text

### Changed
- Improved dark mode: All text now white (#ffffff) for better readability
- Labels and secondary text in light gray (#cccccc) in dark mode

## [0.2.3] - 2025-11-03

### Added
- Automatic connection test on startup
- Intelligent battery status display with charging/discharging/standby states

### Changed
- Price display now in Cents instead of Euro for better readability
- Removed navigation menu for cleaner UI (Dashboard, Konfiguration, Logs links)
- Removed "Verbindung testen" button - now automatic on startup
- Improved dark mode contrast (darker background, pure white text)

### UI
- Battery power status: "Batterie wird geladen/entladen: xxxx W" or "Batterie in Standby"
- Price display: "XX.XX Cent/kWh" instead of "0.XXXX €/kWh"
- Better visibility in dark mode with improved contrast
- Simplified header with only title

## [0.2.2] - 2025-11-03

### Fixed
- Tibber current price now correctly read from sensor state
- Tibber price level correctly read from German level sensor
- Average price calculation from Tibber attributes working
- PV forecast tomorrow now displays correctly (sum of both roofs)

### Changed
- Simplified Tibber price reading logic (removed complex timezone parsing)
- Controller now supports both German and English price levels
- Added automatic dark/light mode detection
- Light mode is now the default for better readability

### UI
- Automatic dark mode activation when system prefers dark color scheme
- Better contrast in both light and dark mode
- Improved overall readability

## [0.2.1] - 2025-11-03

### Changed
- Update interval reduced from 10s to 2s for more responsive UI
- Improved Tibber price parsing to correctly show current price from hourly price array
- Added support for dual-roof PV systems (separate sensors for each roof orientation)
- PV forecast now sums production from both roof orientations
- Price level strings now use English format (CHEAP, EXPENSIVE, etc.)

### Removed
- SOC synchronization feature removed (min/max SOC should be configured directly in inverter)
- Removed `/api/sync_soc` endpoint
- Removed `set_battery_soc_limits()` method from kostal_api
- Removed SOC sync button from dashboard

### Fixed
- Current electricity price now correctly displayed from Tibber sensor attributes
- PV forecast calculation for systems with multiple roof orientations
- Timezone handling for Tibber price matching

### Technical
- Added `get_state_with_attributes()` method to ha_client for full entity data retrieval
- New PV sensor configuration: `pv_power_now_roof1/2`, `pv_remaining_today_roof1/2`, etc.
- Removed legacy `pv_forecast_sensor` and `consumption_sensor` options

## [0.2.0] - 2025-11-03

### Added
- Live battery power display from Home Assistant sensor
- Battery voltage sensor integration (optional)
- SOC limit synchronization to inverter (min/max SOC)
- Live charging power adjustment during active charging
- Automatic optimization mode based on Tibber price levels
- PV forecast integration for smart charging decisions
- New configuration options for sensors and automation:
  - `battery_power_sensor`: Real-time battery power monitoring
  - `battery_voltage_sensor`: Battery voltage monitoring (optional)
  - `tibber_price_sensor`: Tibber price data
  - `tibber_price_level_sensor`: Price level classification
  - `pv_forecast_sensor`: PV generation forecast
  - `consumption_sensor`: Consumption data
  - `auto_optimization_enabled`: Enable/disable automatic optimization
- New API endpoints:
  - `/api/sync_soc`: Synchronize SOC limits to inverter
  - `/api/adjust_power`: Adjust charging power during active charging
- SOC synchronization button in dashboard

### Changed
- Dashboard now shows real-time battery power
- Power slider can adjust charging power during active charging sessions
- Controller loop now includes intelligent auto-optimization logic
- Improved error handling in API endpoints
- Enhanced sensor integration with fallback mechanisms

### Fixed
- Improved error handling for missing or unavailable sensors
- Better state management for charging modes

## [0.1.1] - 2025-10-XX

### Fixed
- Connection test and CORS issues
- Authentication flow improvements

## [0.1.0] - 2025-10-XX

### Added
- Initial release
- Basic battery control via Kostal API
- Modbus TCP integration for charging control
- Home Assistant integration
- Manual charging control
- Tibber integration for price optimization
- Web dashboard with real-time status
