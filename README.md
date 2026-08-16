# Kostal Battery Manager

Home Assistant Add-on für die prognosebasierte Batteriesteuerung von Kostal Plenticore Plus Wechselrichtern.

**Das Ziel ist Autarkie:** Der Speicher soll durch die Sonne so weit gefüllt werden, dass abends und nachts kein Netzstrom gekauft werden muss. Ein leerer Speicher am Abend ist der teure Fall — Bezug kostet deutlich mehr, als Einspeisung einbringt.

Innerhalb dieses Ziels wird die Batterie geschont. Alles, was über den tatsächlichen Bedarf hinaus gespeichert würde, ist keine Autarkie mehr, sondern nur noch Verweildauer bei hohem Ladestand — und die kostet Lebensdauer. Genau diese Differenz nimmt das Add-on heraus, sonst nichts.

Geladen wird ausschließlich mit PV-Überschuss. Das Add-on schreibt keine Leistungs-Sollwerte, sondern nur Grenzen, innerhalb derer die Eigenverbrauchs-Optimierung des Wechselrichters unverändert weiterläuft. Netzladung ist damit strukturell ausgeschlossen — nicht bloß per Bedingung vermieden.

## 🎯 Funktionsprinzip

Klassische Batteriesteuerungen schreiben einen **Leistungs-Sollwert** (Modbus 1034) und erzwingen damit einen Energiefluss. Abends bedeutet das zwangsläufig: die Energie kommt aus dem Netz.

Dieses Add-on schreibt stattdessen nur **Grenzwerte**:

| Register | Bedeutung | Wofür |
|---|---|---|
| 1042 | Minimum SOC (%) | Entladegrenze, Tiefentladeschutz |
| 1044 | Maximum SOC (%) | SOC-Deckel gegen kalendarische Alterung |
| 1038 | Max. Ladeleistung (W) | Drosselung, verteilt die Ladung über den Tag |
| 1040 | Max. Entladeleistung (W) | wird auf dem Gerätewert belassen |

Der Wechselrichter entscheidet weiterhin selbst, wann er lädt — nur eben innerhalb dieses Rahmens.

### Die Hebel

**1. SOC-Deckel.** Aus PV-Prognose für morgen und gelerntem Verbrauch wird berechnet, wieviel Reserve die Batterie wirklich braucht. Kommt morgen viel Sonne, sinkt der Deckel — die Batterie verbringt weniger Zeit bei hohem Ladestand.

Das ist der wichtigste Hebel: Kalendarische Alterung hängt stärker von der **Verweildauer bei hohem SOC** ab als von der Zyklenzahl. Statt der üblichen 10–100 % fährt die Batterie im Normalfall 30–80 %.

**2. Ladeleistungs-Drosselung.** Der Rückstand zum Deckel wird **proportional zur erwarteten Sonne** über den Tag verteilt — nicht gleichmäßig über die Stunden. Fällt 31 % der Restsonne in die aktuelle Stunde, sind auch 31 % des Rückstands erlaubt. Das senkt die C-Rate und verschiebt das Erreichen des Ziel-SOC nach hinten.

Die Rechnung läuft in jedem Regelzyklus neu: Ziehen Wolken auf, steigt die erlaubte Leistung automatisch.

**3. Knappheitserkennung.** Deckt der erwartete Restüberschuss den Rückstand nur knapp, wird **gar nicht gedrosselt**. Drosseln ergibt nur Sinn, wenn mehr Überschuss da ist als gebraucht wird — sonst verteilt man Knappheit und verliert Energie endgültig.

Das ist die Zusage, an der die ganze Strategie hängt: **Gedrosselt wird nur, wenn nachweislich mehr Sonne kommt als der Speicher noch braucht.** Reicht sie knapp — Faktor `throttle_scarcity_factor`, Standard 1,5 — lädt die Batterie mit voller Leistung. Der Speicher wird also nicht deshalb abends leer, weil mittags gedrosselt wurde. Wird es trotz guter Prognose bewölkt, korrigiert sich das von selbst: Die Rechnung läuft alle 30 Sekunden neu, und ein schrumpfender Restüberschuss hebt die erlaubte Leistung sofort wieder an.

Die verbleibende Lücke ist die Prognose selbst. Deshalb wird ihr nur zu `pv_forecast_safety_margin` (Standard 80 %) vertraut — der Rest ist Sicherheitsabstand zugunsten der Autarkie.

**4. Kalibrierladung.** LFP-Zellen brauchen periodisch eine Vollladung, damit das BMS seine SOC-Schätzung nicht wegdriften lässt. Alle `calibration_interval_days` wird an einem Tag mit ausreichender PV-Prognose auf 100 % freigegeben — so kostet es keinen Netzstrom.

### Saisonales Verhalten

Im Winter kehrt sich die Abwägung um. Der Deckel schützt vor langem Verweilen bei hohem Ladestand — dieses Verweilen entsteht aber gar nicht, wenn die Batterie ohnehin jede Nacht tief entladen wird. Was der Deckel dann kostet, ist teurer Netzbezug am Abend.

An **knappen Tagen** (Tagesprognose unter `priority_window_max_pv_kwh`) gilt deshalb:

| | Sommer (38 kWh) | Winter (21 kWh) |
|---|---|---|
| SOC-Korridor | 30–80 % | **25–95 %** |
| nutzbar | 5,3 kWh | **7,5 kWh** |
| 11–15 Uhr | gedrosselt | **volle Ladeleistung** |

Die Umschaltung hängt an der **Tagesprognose, nicht am Kalender** — ein trüber Septembertag wird wie ein Wintertag behandelt. Entscheidend ist die Energielage.

Beachte die Asymmetrie: Der Deckel geht deutlich hoch (80 → 95 %), die Untergrenze nur wenig runter (30 → 25 %). Tiefentladung schadet LFP-Zellen mehr als hoher Ladestand.

### Sicherheit

Fällt der SOC unter `soc_hard_safety_min`, wird das **Entladen gestoppt** — über die SOC-Untergrenze, nicht über ein 0-W-Limit. Ohne Netzladung ist das die einzig sinnvolle Reaktion: die Batterie wartet auf PV, statt weiter leergezogen zu werden.

**Grenzwerte überleben das Add-on.** Ein geschriebener Wert bleibt im Wechselrichter stehen, auch wenn das Add-on stoppt. Daraus folgen zwei Regeln:

- Es wird **nie 0 W** als Grenzwert geschrieben. Ein hängengebliebenes 0-W-Limit würde die Batterie unsichtbar dauerhaft blockieren.
- Beim geordneten Beenden werden alle vier Register auf die beim Start vorgefundenen Werte zurückgesetzt.

## ⚠️ Voraussetzung: Betriebsart des Wechselrichters

Am Kostal-Wechselrichter muss unter *Service → Batterie → Batteriesteuerung* **„Extern über Digital I/O"** eingestellt sein — ohne dass die Digitaleingänge verdrahtet sind.

Das klingt zunächst falsch, ist aber richtig: Ohne angeschlossene Verdrahtung sind alle Eingänge inaktiv, was laut Befehlstabelle des Wechselrichters *„kein externer Zugriff, interne Batteriesteuerung aktiv"* bedeutet. Die interne Optimierung läuft also normal weiter — gleichzeitig ist externes Batteriemanagement nominell aktiv, wodurch die Modbus-Register wirken.

| Modus | SOC-Register | Leistungsregister | Timeout-Blockade |
|---|---|---|---|
| Intern | ❌ ignoriert | ❌ | – |
| **Extern über Digital I/O** | ✅ | ✅ | keine |
| Extern über Modbus TCP | ✅ | ⚠️ | ⚠️ nach Timeout |

- **Intern**: Der Wechselrichter ignoriert alle Steuerregister. Das Add-on hätte keinerlei Wirkung.
- **Modbus TCP**: Die Firmware setzt nach Ablauf des Timeouts beide Leistungsgrenzen auf 0 und **blockiert die Batterie vollständig**. Da diese Strategie bewusst keine Sollwerte schreibt, tritt das zuverlässig ein.

Messwerte zu allen drei Modi in [CONFIGURATION.md](CONFIGURATION.md).

## 📋 Voraussetzungen

- Home Assistant OS oder Supervised
- Kostal Plenticore Plus, Firmware 01.30.x oder neuer
- Modbus TCP am Wechselrichter aktiviert, Betriebsart „Extern über Digital I/O"
- Standortkoordinaten und Dachdaten für die PV-Prognose
- Verbrauchssensor für das Verbrauchslernen
- Aufgezeichnete SOC-Historie in Home Assistant (für die Wirkungskontrolle)

## 🚀 Installation

1. Repository in Home Assistant hinzufügen:
   Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories →
   `https://github.com/kaiser1101/kostal-battery-manager`
2. „Kostal Battery Manager" installieren
3. Konfigurieren (siehe unten), speichern, starten

## ⚙️ Inbetriebnahme

### Schritt 0: PV-Prognose sicherstellen

**Ohne stündliche PV-Prognose bewirkt das Add-on nichts** — keine Drosselung, kein SOC-Deckel, keine Kalibrierung. Der API-Key ist optional; ohne Key wird die öffentliche Schnittstelle genutzt:

```yaml
enable_forecast_solar_api: true
forecast_solar_api_key: ''           # leer = öffentliche API
forecast_solar_latitude: 48.2085     # DEINE Koordinaten eintragen
forecast_solar_longitude: 16.3721
forecast_solar_roof1_declination: 42
forecast_solar_roof1_azimuth: 0      # 0=Süd, 90=West, -90=Ost
forecast_solar_roof1_kwp: 5.1
forecast_solar_roof2_kwp: 0          # 0 = nur eine Dachfläche
```

Im Log muss danach stehen:

```
✓ Forecast.Solar: 30 Stundenwerte fuer 2 Tage abgerufen (1 Abruf(e))
```

Der sensorbasierte Fallback (`pv_production_today_roof1/2` mit Attribut `wh_hours`) funktioniert nur mit älteren Versionen der HA-Integration.

### Schritt 1: Registerdiagnose prüfen

Beim Start protokolliert das Add-on, was es am Wechselrichter vorfindet — **rein lesend**, also auch im Dry-Run:

```
--- Registerdiagnose ---
  1068 Batteriekapazitaet : 10656 Wh (10.7 kWh) | konfiguriert: 10.7 kWh
  1080 Management-Modus    : Extern via digital I/O (Rohwert 1)
  1038 Max. Ladeleistung   : 4450.9 W
  1042 Minimum SOC         : 10.0 %
  1044 Maximum SOC         : 100.0 %
  -> Limit-Register lesbar, Steuerung sollte funktionieren
------------------------
```

Steht dort `NICHT lesbar`, wird die Strategie an diesem Gerät nicht funktionieren.

Zusätzlich gibt es im Dashboard zwei Prüfungen:

- **🔬 Registertest** — schreibt je Register einen minimal veränderten Wert und stellt das Original sofort wieder her. Zeigt, ob der Wechselrichter Schreibzugriffe annimmt.
- **⏱️ Haltetest** — schreibt 2000 W auf Register 1038 und beobachtet 3 Minuten, ob der Wert stehen bleibt. Beantwortet, ob ein Grenzwert über Minuten *hält* — Lesbarkeit allein beweist das nicht.

### Schritt 2: Im Dry-Run beobachten

`dry_run: true` ist der Standard. Es wird nichts geschrieben; jede Entscheidung landet nur im Log und im Dashboard.

```yaml
charging_strategy: "forecast"
dry_run: true
battery_capacity: 10.7
max_charge_power: 4300
```

Im Dashboard zeigt die Karte **🛡️ Batterieschonung** mit `DRY-RUN`-Badge, welche Grenzen gesetzt *würden* — samt Begründung und dem zurückgelesenen Ist-Zustand des Wechselrichters. Die Differenz ist genau das, was sich beim Scharfschalten ändern würde.

Prüfe: Passt der Überbrückungsbedarf? Beruht er auf echten Messwerten oder auf dem Fallback? Die stundenweise Aufschlüsselung steht im Log.

### Schritt 3: Ausgangsbasis festhalten

Führe **vor** dem Scharfschalten einmal die Wirkungskontrolle aus und notiere die Zahlen. Danach ist der Vorher-Zustand nicht mehr rekonstruierbar.

Für einen belastbaren Vergleich solltest du vorher die Aufbewahrungszeit erhöhen — HA hält standardmäßig nur rund 10 Tage vor:

```yaml
recorder:
  purge_keep_days: 60
```

### Schritt 4: Scharfschalten

`dry_run: false`, neu starten. Im Log muss stehen:

```
Min SOC 30.0% = 30.0 (Register 1042)          ← ohne [DRY-RUN]
Wechselrichter bestaetigt: SOC-Korridor 30.0-80.0%, laden max 500.0W
```

Die Bestätigungszeile ist der Rückleseabgleich: Der Wechselrichter meldet die Werte zurück. Weicht etwas ab, erscheint stattdessen eine Warnung.

Zur unabhängigen Kontrolle: Im Kostal-Webinterface unter *Batterieeinstellungen* muss der **Min. Ladezustand** jetzt den konfigurierten Wert zeigen — das ist dasselbe Register 1042.

**Zurückfallen ist gefahrlos:** `dry_run: true` setzen und neu starten. Das Add-on gibt beim Beenden alle Register auf die Ausgangswerte frei.

## 🔧 Wichtige Parameter

| Parameter | Standard | Bedeutung |
|---|---|---|
| `charging_strategy` | `forecast` | `forecast` = PV-Shaping, `price` = alte Tibber-Logik |
| `dry_run` | `true` | Keine Schreibzugriffe, nur Logging |
| `soc_corridor_min` | 30 | Entladegrenze an normalen Tagen (%) |
| `soc_corridor_max` | 80 | Obergrenze an normalen Tagen (%) |
| `soc_corridor_min_scarce` | 25 | Entladegrenze an knappen Tagen (%) |
| `soc_corridor_max_scarce` | 95 | Obergrenze an knappen Tagen (%) |
| `soc_hard_safety_min` | 15 | Notbremse: darunter Entladen gestoppt (%) |
| `priority_window_start/_end` | 11 / 15 | Vorrangfenster: keine Drosselung an knappen Tagen |
| `priority_window_max_pv_kwh` | 25.0 | Ab welcher Tagesprognose ein Tag als knapp gilt |
| `throttle_scarcity_factor` | 1.5 | Ab welcher Überdeckung überhaupt gedrosselt wird |
| `enable_charge_throttling` | `true` | Ladung über die PV-Stunden verteilen |
| `min_charge_power` | 500 | Untergrenze der gedrosselten Leistung (W) |
| `calibration_interval_days` | 28 | Abstand der Kalibrierladungen, 0 = aus |
| `pv_forecast_safety_margin` | 0.8 | Anteil der PV-Prognose, dem vertraut wird |
| `enable_forecast_solar_api` | `false` | Direkter API-Zugriff — **empfohlen**, siehe Schritt 0 |
| `publish_ha_sensors` | `true` | Plan als HA-Entitäten veröffentlichen |

Vollständige Erklärungen in [CONFIGURATION.md](CONFIGURATION.md).

### Verbrauchslernen

Das Add-on lernt das stündliche Verbrauchsprofil aus `home_consumption_sensor` über `learning_period_days` (Standard 28 Tage). Ein manuelles Lastprofil gibt es nicht — es hätte gegen die echten Messwerte konkurriert. Bis genug Daten vorliegen, greift `default_hourly_consumption_fallback` bzw. `average_daily_consumption / 24`.

Historische Daten lassen sich über die Seite „Verbrauchsimport" per CSV oder direkt aus Home Assistant einspielen. Das verkürzt die Anlaufphase erheblich.

## 📊 Dashboard

- **🛡️ Batterieschonung** — der aktuelle Plan: SOC-Korridor, Ladegrenze, Begründung im Klartext, Überbrückungsbedarf, Fehlbetrag morgen, zurückgelesener Registerzustand. Dazu Registertest und Haltetest.
- **🔋 Batterie-Prognose** — SOC-Verlauf: gemessen bis zur aktuellen Stunde, danach projiziert. Nach Sonnenuntergang wird der morgige Tag gezeigt.
- **📈 Wirkungskontrolle** — Verweildauer über dem Korridor, vorher gegen nachher.
- **📊 Verbrauchslernen** — Abdeckung und Datenbasis.

In der `forecast`-Strategie werden die preisbasierten Karten ausgeblendet.

## 🏠 Home-Assistant-Entitäten

Mit `publish_ha_sensors: true` (Standard) veröffentlicht das Add-on seinen Plan als HA-Entitäten. Der Recorder schreibt sie mit — damit gibt es Verlauf, Diagramme und Auslöser für Automatisierungen:

| Entität | Bedeutung |
|---|---|
| `sensor.kostal_bm_target_soc` | Aktueller SOC-Deckel (%) |
| `sensor.kostal_bm_min_soc` | Aktuelle Entladegrenze (%) |
| `sensor.kostal_bm_max_charge_power` | Aktuelle Ladeleistungsgrenze (W) |
| `sensor.kostal_bm_bridging_need` | Überbrückungsbedarf bis Sonnenaufgang (kWh) |
| `sensor.kostal_bm_tomorrow_shortfall` | Fehlbetrag morgen (kWh) |
| `sensor.kostal_bm_pv_forecast_today` | PV-Prognose heute (kWh) |
| `sensor.kostal_bm_status` | `normal`, `safety` oder `calibration` |

Der Status-Sensor trägt die **Begründung als Attribut** — im Verlauf ist damit nachvollziehbar, warum eine Entscheidung fiel, nicht nur welche.

## 📈 Wirkungskontrolle

Beantwortet die Frage, die am Ende zählt: Hat die Strategie etwas gebracht?

```
VORHER  (ohne Strategie)   (1 Tag, 111 Messpunkte)
   Ladestand im Mittel     74.7 %   (min 46 / max 100)
   ueber 80 %              10.5 h  = 44.3 % der Zeit
   ueber 95 %               8.3 h  = 34.9 % der Zeit
   Vollzyklen              0.53  (0.54 pro Tag)
```

Gemessen wird die **Verweildauer bei hohem Ladestand**. Die Trennlinie ist der Zeitpunkt des ersten echten Schreibvorgangs, der automatisch vermerkt wird.

Zwei Details, ohne die die Zahlen falsch wären: Die Zeitanteile werden über die **Dauer zwischen den Messpunkten** gewichtet, nicht über deren Anzahl — HA schreibt nur bei Änderung. Und ein stundenlang konstanter SOC erzeugt gar keine Einträge; solche Lücken werden bis zu 12 Stunden als gültige Messung behandelt, weil sie fast immer konstanten Ladestand bedeuten und nicht fehlende Daten.

Umfasst ein Zeitraum weniger als 7 Tage, weist die Auswertung selbst darauf hin, dass das Ergebnis **nicht belastbar** ist.

## 🛡️ Sicherheitshinweise

- Das Add-on greift direkt auf den Wechselrichter zu. Falsche Werte können die Batterie schädigen.
- **Beginne immer im Dry-Run.**
- Beachte die Garantiebedingungen deines Batterieherstellers, insbesondere zu Entladetiefe und Zyklenzahl.
- Der Modbus-Port sollte nicht aus dem Internet erreichbar sein (kein Port-Forwarding).
- Eigene Sensornamen und Koordinaten gehören in die Add-on-Konfiguration von Home Assistant, **nicht** in `config.yaml` — die Datei enthält die Vorgaben für alle Nutzer und wird veröffentlicht.

## 📖 Technische Referenz

Registerangaben nach *KOSTAL Interface MODBUS-TCP / SunSpec with Control*, Kap. 3.4 „External battery management":

- **1038 / 1040** — max. Lade- bzw. Entladeleistung, W, Float32, RW
- **1042 / 1044** — Minimum / Maximum SOC, %, Float32, RW
- **1068** — Batteriekapazität in Wh, RO
- **1080** — Batteriemanagement-Modus, U8, RO: 0 = keins, 1 = digital I/O, 2 = Modbus
- **1034** — Ladesollwert, W, Float32, RW. Negativ = laden, positiv = entladen. **Wird von der `forecast`-Strategie nicht verwendet**, da ein Sollwert bei Nacht Netzstrom zieht.
- **5** — eingestellte Byte Order: 0 = Little-endian (CDAB, Default), 1 = Big-endian (ABCD, SunSpec). Wird beim Start gelesen und die Wortreihenfolge entsprechend angepasst.

TCP-Port 1502, Unit-ID 71 (beide am Gerät änderbar).

> Hinweis der Kostal-Doku: Die Sollwert-Register 1028/1032/1034/1036 unterliegen in Dänemark und Österreich normativen Gradientenbeschränkungen. Die hier genutzten Limit-Register sind davon nicht betroffen.

### Eigenheiten der Leistungsregister

Register 1038/1040 werden von der Firmware laufend mit der momentanen Leistungsfähigkeit der Batterie überschrieben — beobachtbar als Pendeln zwischen zwei Werten. Ein deutlich **niedrigerer** Grenzwert bleibt dagegen stehen: An realer Hardware hielt ein Limit von 2000 W über drei Minuten unverändert.

Praktische Folge: Ein Schreibtest, der nur knapp unter den Ist-Wert geht, liefert widersprüchliche Ergebnisse. Der Haltetest im Dashboard schreibt deshalb mit deutlichem Abstand.

## 📝 Changelog

Siehe [CHANGELOG.md](CHANGELOG.md).

## 📄 Lizenz

MIT — siehe [LICENSE](LICENSE).

## 🙏 Credits

- **Kilian Knoll** — ursprüngliche `batctl.py`-Implementierung der Kostal REST API
- **Home Assistant Community**
