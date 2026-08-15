# Konfigurations-Anleitung

Diese Anleitung beschreibt die Strategie `charging_strategy: forecast` (Standard seit v0.10.0).
Für die alte preisbasierte Logik siehe den Abschnitt [Legacy: Preisstrategie](#legacy-preisstrategie).

## Grundeinstellungen

### `dry_run` (Standard: `true`)

Im Dry-Run wird **nichts** auf den Wechselrichter geschrieben. Alle Entscheidungen erscheinen nur im Log und im Dashboard.

**Lass das beim ersten Start unbedingt an.** Erst wenn die geplanten Grenzwerte über mehrere Tage plausibel aussehen, auf `false` stellen.

### `battery_soc_sensor`

Der Batterie-SOC-Sensor aus Home Assistant, z. B. `sensor.zwh8_8500_battery_soc`.

Zu finden unter: Entwicklerwerkzeuge → Zustände → nach „battery" oder „soc" suchen. Der Wert muss zwischen 0 und 100 liegen.

### `battery_capacity`

Nutzbare Kapazität in kWh. Wird für alle Energieberechnungen verwendet — ein falscher Wert verzerrt Nachtbedarf und SOC-Deckel direkt.

Der Wechselrichter meldet die Kapazität selbst in Register 1068; beim Verbindungstest steht sie im Log und lässt sich damit gegenprüfen.

## Der SOC-Korridor

```
100% ┌─────────────────────────┐
     │                         │
     │  soc_corridor_max (80)  │  ← Obergrenze für normales Laden
     │  ░░░░░░░░░░░░░░░░░░░░░  │
     │  ░ Arbeitsbereich ░░░░  │
     │  ░░░░░░░░░░░░░░░░░░░░░  │
     │  soc_corridor_min (30)  │  ← Entladen stoppt hier
     │                         │
     │  soc_hard_safety_min(15)│  ← Notbremse: Entladen komplett gesperrt
  0% └─────────────────────────┘
```

### `soc_corridor_min` (Standard: 30 %)

Untergrenze für das Entladen (Register 1042). Schützt vor tiefen Zyklen.

Höhere Werte schonen die Batterie, verkleinern aber den nutzbaren Bereich.

### `soc_corridor_max` (Standard: 80 %)

Obergrenze für das Laden (Register 1044). Verhindert routinemäßiges Vollladen.

Der tatsächliche Deckel wird **dynamisch** berechnet und liegt oft darunter — nämlich dann, wenn die morgige PV-Prognose gut ist und die Batterie weniger Reserve braucht.

> **Wichtige Einschränkung:** Der dynamische Deckel greift nur, wenn deine Batterie groß genug relativ zum Nachtverbrauch ist. Rechenbeispiel: 10,6 kWh Kapazität, 0,7 kWh/h Verbrauch, 13 Stunden Nacht → 9,1 kWh Nachtbedarf. Das sind 86 % der Kapazität. Zusammen mit `soc_corridor_min` von 30 % ergibt sich rechnerisch ein Ziel über 100 %, also bleibt der Deckel dauerhaft bei 80 %.
>
> Prüfe daher deinen tatsächlichen Tagesverbrauch. Liegt er deutlich niedriger, lohnt es sich, `soc_corridor_max` zu senken, damit der Hebel überhaupt Spielraum hat.

### `soc_hard_safety_min` (Standard: 15 %)

Notbremse. Darunter wird das **Entladen gesperrt** (Register 1040 = 0 W).

Da nie aus dem Netz geladen wird, ist das die einzig sinnvolle Reaktion auf einen kritisch tiefen SOC: die Batterie wartet auf PV, statt weiter leergezogen zu werden.

## Ladeleistungs-Drosselung

### `enable_charge_throttling` (Standard: `true`)

Verteilt die noch fehlende Energie über die verbleibenden PV-Stunden, statt vormittags mit voller Leistung zu laden.

**Beispiel:** 3,7 kWh fehlen, 10 Stunden bis Sonnenuntergang → 370 W statt 3900 W.

Zwei Effekte: niedrigere C-Rate, und der Ziel-SOC wird erst gegen Abend erreicht statt am Vormittag. Letzteres ist der wirksamste Hebel gegen langes Verweilen bei hohem SOC.

Die Rechnung läuft in **jedem** Regelzyklus neu. Ziehen Wolken auf und der SOC bleibt zurück, steigt die erlaubte Leistung automatisch — das System korrigiert sich selbst.

### `min_charge_power` (Standard: 500 W)

Untergrenze der gedrosselten Leistung. Verhindert, dass bei winzigem Restbedarf unrealistisch kleine Werte gesetzt werden.

### Nachtsperre (automatisch)

Außerhalb der PV-Stunden wird das Ladelimit auf **0 W** gesetzt. Ladung könnte dort nur aus dem Netz kommen. Das ist nicht konfigurierbar und folgt direkt aus dem Grundsatz „keine Netzladung".

## Kalibrierladung

### `calibration_interval_days` (Standard: 28, `0` = aus)

LFP-Zellen brauchen periodisch eine Vollladung, damit das BMS seine SOC-Schätzung neu kalibrieren kann. Ohne das driftet die Anzeige mit der Zeit weg — und da alle Berechnungen auf dem SOC beruhen, würde die ganze Steuerung ungenau.

### `calibration_min_pv_kwh` (Standard: 15.0)

Die Kalibrierung wird nur an Tagen ausgelöst, an denen mindestens so viel PV prognostiziert ist. So kostet die Vollladung keinen Netzstrom.

Ist die Kalibrierung fällig, aber die Prognose zu schwach, wartet das Add-on auf einen besseren Tag.

Bei Erstinstallation wird das Intervall **ab dem Installationstag** gerechnet — die erste Kalibrierung erfolgt also nach `calibration_interval_days`, nicht sofort.

## PV-Prognose

### `pv_forecast_safety_margin` (Standard: 0.8)

Anteil der PV-Prognose, dem vertraut wird. Bei 0.8 wird mit 80 % des prognostizierten Ertrags gerechnet.

Niedriger = konservativer = mehr Reserve = höherer SOC-Deckel.

### `pv_dropoff_threshold` (Standard: 0.05)

Ab welchem Bruchteil des Tagesmaximums eine Stunde noch als „PV-Stunde" gilt. Bestimmt die erkannten Sonnenauf- und -untergangszeiten.

### Forecast.Solar — die wichtigste Datenquelle

**Ohne stündliche PV-Prognose ist die gesamte Strategie wirkungslos.** Es gibt dann keine Drosselung, keinen SOC-Deckel und keine Kalibrierung — das Add-on läuft, tut aber nichts. Deshalb lohnt es sich, diesen Abschnitt sorgfältig zu prüfen.

**Empfohlen: direkter API-Zugriff.** Seit v0.10.2 ist der API-Key **optional** — ohne Key wird die öffentliche Schnittstelle genutzt:

```yaml
enable_forecast_solar_api: true
forecast_solar_api_key: ''              # leer lassen = öffentliche API
forecast_solar_latitude: 48.2085
forecast_solar_longitude: 16.3721
forecast_solar_roof1_declination: 42    # Dachneigung 0-90°
forecast_solar_roof1_azimuth: 0         # 0=Süd, 90=West, -90=Ost, ±180=Nord
forecast_solar_roof1_kwp: 5.1
forecast_solar_roof2_declination: 42    # zweite Fläche, sonst kWp auf 0
forecast_solar_roof2_azimuth: 0
forecast_solar_roof2_kwp: 2.5
```

Zwingend sind nur **Koordinaten**; fehlen sie, bleibt die API aus. Ein Abruf deckt **heute und morgen** ab und wird 15 Minuten zwischengespeichert — das hält die freie Nutzung im Ratelimit. Ein Key erhöht nur das Limit, die Daten sind dieselben.

**Fallback: HA-Sensoren.** Alternativ liest das Add-on `pv_production_today_roof1/2` und erwartet dort ein Attribut `wh_hours` mit Stundenwerten.

> ⚠️ Neuere Versionen der HA-Forecast.Solar-Integration stellen dieses Attribut **nicht mehr** bereit — die Stundenwerte liegen dort nur noch im Energie-Dashboard. Im Log erscheint dann:
> ```
> Roof1 sensor sensor.energy_production_today has no 'wh_hours' attribute
> No hourly PV forecast data available
> ```
> In dem Fall führt kein Weg an der API vorbei. Wechselrichter-Sensoren (gemessene Erträge) funktionieren hier grundsätzlich nicht — das sind Messwerte, keine Prognose.

**Mehrere Dachflächen:** Jede Fläche braucht eigene Neigung, Ausrichtung und kWp. Nur wenn die Geometrie wirklich abweicht, entstehen unterschiedliche Tageskurven — identische Werte ergeben lediglich dieselbe Kurve in anderem Maßstab. Für nur eine Fläche `forecast_solar_roof2_kwp: 0` setzen.

## Verbrauchslernen

### `home_consumption_sensor`

Der Hausverbrauchssensor. Einheiten W, kW und kWh werden automatisch erkannt.

### `learning_period_days` (Standard: 28)

Lernzeitraum in Tagen. Vier Wochen fangen Wochentagsmuster gut ein.

### `default_hourly_consumption_fallback`

Fallback, solange für eine Stunde noch keine Daten vorliegen. Alternativ `average_daily_consumption` angeben — das wird durch 24 geteilt.

> **Seit v0.10.0 gibt es kein `manual_load_profile` mehr.** Ein handgeschriebenes Profil hätte gegen die echten Messwerte konkurriert. Zum Beschleunigen der Anlaufphase stattdessen die Seite „Verbrauchsimport" nutzen: CSV-Upload oder Direktimport der Historie aus Home Assistant.

## Fehlersuche

### „Warte auf ersten Plan"

Der Plan wird im `control_interval` (Standard 30 s) berechnet. Erscheint dauerhaft nichts, prüfe:
- Ist `auto_optimization_enabled: true`?
- Läuft die Automatik (Toggle im Dashboard)?
- Liefert `battery_soc_sensor` einen Wert?

### SOC-Deckel bleibt immer bei `soc_corridor_max`

Siehe die Einschränkung oben — dein Nachtbedarf übersteigt vermutlich den nutzbaren Korridor. Prüfe im Dashboard den Wert „Nachtbedarf" gegen deine Kapazität.

### Zurückgelesene Werte weichen ab

Erscheint im Log `Register-Rueckmeldung weicht ab`, akzeptiert der Wechselrichter die Limits nicht. Mögliche Ursachen:
- Falsche Byte Order (das Add-on prüft Register 5 beim Start — siehe Log)
- Firmware zu alt
- Batteriemanagement-Modus passt nicht (Register 1080 im Log)

### Ladeleistung wirkt zu niedrig

Das ist meist Absicht: die Drosselung verteilt die Ladung über den Tag. Die Begründung im Dashboard nennt die Rechnung, z. B. „3.7 kWh auf 10h bis Sonnenuntergang verteilt".

---

## Legacy: Preisstrategie

Mit `charging_strategy: price` läuft die alte, Tibber-basierte Logik mit `auto_safety_soc`, `auto_charge_below_soc`, `auto_pv_threshold` und den `tibber_price_threshold_*`-Parametern.

⚠️ **Diese Strategie lädt aus dem Netz.** Sie schreibt Setpoints auf Register 1034 und ist mit dem Ziel „keine Netzladung" unvereinbar. Sie bleibt nur aus Kompatibilitätsgründen erhalten.
