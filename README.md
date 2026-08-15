# Kostal Battery Manager

Home Assistant Add-on für die prognosebasierte Batteriesteuerung von Kostal Plenticore Plus Wechselrichtern.

**Ziel des Add-ons ist die Lebensdauer der Batterie, nicht die maximale Ersparnis.** Es lädt niemals aus dem Netz. Stattdessen gibt es dem Wechselrichter nur Grenzen vor, innerhalb derer dessen eigene Eigenverbrauchs-Optimierung weiterläuft.

## 🎯 Funktionsprinzip

Klassische Batteriesteuerungen schreiben einen **Leistungs-Setpoint** (Modbus 1034) und erzwingen damit einen Energiefluss. Abends bedeutet das zwangsläufig: die Energie kommt aus dem Netz.

Dieses Add-on macht das Gegenteil. Es schreibt ausschließlich **Grenzwerte**:

| Register | Bedeutung | Hebel |
|---|---|---|
| 1038 | Max. Ladeleistung (W) | Drosselung + Nachtsperre |
| 1040 | Max. Entladeleistung (W) | Tiefentladeschutz |
| 1042 | Minimum SOC (%) | Entladegrenze |
| 1044 | Maximum SOC (%) | Dynamischer SOC-Deckel |

Der Wechselrichter entscheidet weiterhin selbst, wann er lädt — nur eben innerhalb dieses Rahmens. Netzladung ist damit **strukturell ausgeschlossen**, nicht bloß per Bedingung vermieden.

### Die vier Hebel

**1. Dynamischer SOC-Deckel.** Aus PV-Prognose für morgen und gelerntem Verbrauch wird berechnet, wieviel Reserve die Batterie wirklich braucht. Kommt morgen viel Sonne, wird der Deckel gesenkt — die Batterie verbringt weniger Zeit bei hohem SOC, was die kalendarische Alterung reduziert.

> ⚠️ Dieser Hebel greift nur, wenn die Batterie **groß relativ zum Nachtverbrauch** ist. Bei 10,6 kWh Kapazität und ~17 kWh Tagesverbrauch übersteigt allein der Nachtbedarf (~9 kWh) den verfügbaren Korridor — der Deckel bleibt dann dauerhaft bei `soc_corridor_max`. Prüfe deinen realen Verbrauch, bevor du dir davon etwas versprichst.

**2. Ladeleistungs-Drosselung.** Die noch fehlende Energie wird über die verbleibenden PV-Stunden verteilt, statt vormittags mit voller Leistung durchzuladen. Das senkt die C-Rate und verschiebt das Erreichen des Ziel-SOC nach hinten. Die Rechnung läuft in jedem Regelzyklus neu — ziehen Wolken auf, steigt die Leistung automatisch wieder.

**3. Nachtsperre.** Außerhalb der PV-Stunden wird das Ladelimit auf 0 W gesetzt. Ladung könnte dort nur aus dem Netz kommen.

**4. Kalibrierladung.** LFP-Zellen brauchen periodisch eine Vollladung, damit das BMS seine SOC-Schätzung nicht wegdriften lässt. Alle `calibration_interval_days` wird an einem Tag mit ausreichender PV-Prognose auf 100 % freigegeben — so kostet es keinen Netzstrom.

### Sicherheit

Fällt der SOC unter `soc_hard_safety_min`, wird das **Entladen gesperrt** (Register 1040 = 0). Ohne Netzladung ist das die einzig sinnvolle Reaktion: die Batterie wartet auf PV, statt weiter leergezogen zu werden.

## ⚠️ Voraussetzung: Betriebsart des Wechselrichters

Am Kostal-Wechselrichter muss unter *Service → Batterie → Batteriesteuerung* **„Extern über Protokoll (Digital I/O)"** eingestellt sein. Ohne Verdrahtung der Digitaleingänge läuft die interne Eigenverbrauchs-Optimierung normal weiter — aber die Modbus-Grenzwerte wirken.

- **Intern**: Der Wechselrichter ignoriert alle Steuerregister. Das Add-on hätte keine Wirkung.
- **Modbus TCP**: Die Firmware blockiert die Batterie nach Ablauf des Timeouts, weil diese Strategie bewusst keine Setpoints schreibt.

Details und Messwerte in [CONFIGURATION.md](CONFIGURATION.md).

## 📋 Voraussetzungen

- Home Assistant OS oder Supervised
- Kostal Plenticore Plus, Firmware 01.30.x oder neuer
- Modbus TCP am Wechselrichter aktiviert
- PV-Prognose: Forecast.Solar (API ohne Key nutzbar, siehe unten)
- Verbrauchssensor für das Verbrauchslernen

## 🚀 Installation

1. Repository in Home Assistant hinzufügen:
   Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories →
   `https://github.com/kaiser1101/kostal-battery-manager`
2. „Kostal Battery Manager" installieren
3. Konfigurieren (siehe unten), speichern, starten

## ⚙️ Inbetriebnahme

### Schritt 0: PV-Prognose sicherstellen

**Ohne stündliche PV-Prognose bewirkt das Add-on nichts** — keine Drosselung, kein SOC-Deckel, keine Kalibrierung. Der einfachste zuverlässige Weg ist der direkte API-Zugriff; ein Key ist seit v0.10.2 **nicht** nötig:

```yaml
enable_forecast_solar_api: true
forecast_solar_api_key: ''           # leer = öffentliche API
forecast_solar_latitude: 48.2085     # deine Koordinaten
forecast_solar_longitude: 16.3721
forecast_solar_roof1_declination: 42
forecast_solar_roof1_azimuth: 0      # 0=Süd, 90=West, -90=Ost
forecast_solar_roof1_kwp: 5.1
forecast_solar_roof2_kwp: 0          # 0 = nur eine Dachfläche
```

Im Log muss danach stehen:
```
✓ Forecast.Solar: 30 Stundenwerte fuer 2 Tage abgerufen
```

Der sensorbasierte Fallback (`pv_production_today_roof1/2` mit Attribut `wh_hours`) funktioniert nur mit älteren Versionen der HA-Integration. Details in [CONFIGURATION.md](CONFIGURATION.md).

### Schritt 1: Im Dry-Run starten

`dry_run: true` ist der **Standard und sollte es zunächst bleiben.** In diesem Modus wird nichts auf den Wechselrichter geschrieben — jede Entscheidung landet nur im Log und im Dashboard.

```yaml
charging_strategy: "forecast"
dry_run: true
battery_capacity: 10.6
max_charge_power: 3900
```

Lass das eine Woche laufen. Im Dashboard zeigt die Karte **🛡️ Batterieschonung** mit `DRY-RUN`-Badge, welche Grenzen gesetzt *würden*, samt Begründung und den Zwischenwerten (Nachtbedarf, Fehlbetrag morgen).

### Schritt 2: Prüfen

Im Log solltest du beim Start sehen:

```
Byte Order: Little-endian (CDAB) - Default, passt zur Implementierung
Battery management mode: ... (Register 1080 = ...)
Modbus test successful, Battery work capacity: ... Wh
```

Steht dort stattdessen **Big-endian (ABCD/SunSpec)**, hat das Add-on die Wortreihenfolge automatisch umgestellt — ohne diese Prüfung wären alle Float-Register unbrauchbar.

Vergleiche die geplanten Grenzen mit dem, was deine Anlage tatsächlich getan hat. Passt der Nachtbedarf? Ist der SOC-Deckel realistisch?

### Schritt 3: Scharfschalten

Erst wenn die Logs plausibel aussehen: `dry_run: false`. Danach zeigt das Dashboard zusätzlich die aus den Registern **zurückgelesenen** Werte — weicht dort etwas ab, akzeptiert der Wechselrichter die Limits nicht, und es erscheint eine Warnung im Log.

## 🔧 Wichtige Parameter

| Parameter | Standard | Bedeutung |
|---|---|---|
| `charging_strategy` | `forecast` | `forecast` = PV-Shaping, `price` = alte Tibber-Logik |
| `dry_run` | `true` | Keine Schreibzugriffe, nur Logging |
| `soc_corridor_min` | 30 | Weiche Entladegrenze (%) |
| `soc_corridor_max` | 80 | Obergrenze, kein routinemäßiges Vollladen (%) |
| `soc_hard_safety_min` | 15 | Notbremse: darunter Entladen gesperrt (%) |
| `enable_charge_throttling` | `true` | Ladung über die PV-Stunden verteilen |
| `min_charge_power` | 500 | Untergrenze der gedrosselten Leistung (W) |
| `calibration_interval_days` | 28 | Abstand der Kalibrierladungen, 0 = aus |
| `calibration_min_pv_kwh` | 15.0 | Kalibrierung nur an Tagen mit dieser PV-Prognose |
| `pv_forecast_safety_margin` | 0.8 | Anteil der PV-Prognose, dem vertraut wird |
| `enable_forecast_solar_api` | `false` | Direkter API-Zugriff — **empfohlen**, siehe Schritt 0 |
| `forecast_solar_api_key` | `''` | Optional. Leer = öffentliche API |

### Verbrauchslernen

Das Add-on lernt das stündliche Verbrauchsprofil aus `home_consumption_sensor` über `learning_period_days` (Standard 28 Tage). **Ein manuelles Lastprofil gibt es seit v0.10.0 nicht mehr** — es hätte gegen die echten Messwerte konkurriert. Bis genug Daten vorliegen, greift `default_hourly_consumption_fallback` bzw. `average_daily_consumption / 24`.

Historische Daten lassen sich über die Seite „Verbrauchsimport" per CSV oder direkt aus Home Assistant einspielen. Das verkürzt die Anlaufphase erheblich.

## 📊 Dashboard

- **🛡️ Batterieschonung** — der aktuelle Plan: SOC-Korridor, Lade-/Entladegrenzen, Begründung, Nachtbedarf, Fehlbetrag morgen. Im Scharfbetrieb zusätzlich die zurückgelesenen Registerwerte.
- **🔋 Batterie** — SOC und aktueller Fluss
- **☀️ PV Prognose** — heute und morgen
- **📊 Verbrauchslernen** — Fortschritt und Datenbasis

In der `forecast`-Strategie werden die preisbasierten Karten ausgeblendet, da Strompreise dort keine Rolle spielen.

## 🛡️ Sicherheitshinweise

- Das Add-on greift direkt auf den Wechselrichter zu. Falsche Werte können die Batterie schädigen.
- **Beginne immer im Dry-Run.**
- Beachte die Garantiebedingungen deines Batterieherstellers, insbesondere zu Entladetiefe und Zyklenzahl.
- Der Modbus-Port sollte nicht aus dem Internet erreichbar sein (kein Port-Forwarding).

## 📖 Technische Referenz

Registerangaben nach *KOSTAL Interface MODBUS-TCP / SunSpec with Control*, Kap. 3.4 „External battery management":

- **1038 / 1040** — max. Lade- bzw. Entladeleistung, W, Float32, RW
- **1042 / 1044** — Minimum / Maximum SOC, %, Float32, RW
- **1068** — Batteriekapazität in Wh, RO *(in früheren Versionen fälschlich als SOC beschriftet)*
- **1080** — Batteriemanagement-Modus, U8, RO: 0 = keins, 1 = digital I/O, 2 = Modbus
- **1034** — Ladesetpoint, W, Float32, RW. Negativ = laden, positiv = entladen. **Wird von der `forecast`-Strategie nicht verwendet**, da ein Setpoint bei Nacht Netzstrom zieht.
- **5** — eingestellte Byte Order: 0 = Little-endian (CDAB, Default), 1 = Big-endian (ABCD, SunSpec)

TCP-Port 1502, Unit-ID 71 (beide am Gerät änderbar).

> Hinweis der Kostal-Doku: Die Setpoint-Register 1028/1032/1034/1036 unterliegen in Dänemark und Österreich normativen Gradientenbeschränkungen. Die hier genutzten Limit-Register sind davon nicht betroffen.

## 📝 Changelog

Siehe [CHANGELOG.md](CHANGELOG.md). Wesentliche Änderung in v0.10.0: prognosebasiertes PV-Shaping ersetzt die netzladende „Evening Top-up"-Logik.

## 📄 Lizenz

MIT — siehe [LICENSE](LICENSE).

## 🙏 Credits

- **Kilian Knoll** — ursprüngliche `batctl.py`-Implementierung der Kostal REST API
- **Home Assistant Community**
