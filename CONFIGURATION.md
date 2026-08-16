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

### `soc_corridor_max_scarce` (Standard: 95 %)

Obergrenze an **knappen Tagen** — also wenn die Tagesprognose unter `priority_window_max_pv_kwh` liegt.

**Warum die Abwägung im Winter kippt:** Der Deckel schützt vor langem Verweilen bei hohem Ladestand. Im Winter wird die Batterie aber ohnehin jede Nacht tief entladen — dieses Verweilen entsteht dort gar nicht erst. Was der Deckel dann kostet, ist teurer Netzbezug am Abend.

| Tag | Korridor | nutzbar |
|---|---|---|
| Sommer (38 kWh Prognose) | 30–80 % | 5,3 kWh |
| Winter (21 kWh Prognose) | 30–95 % | 7,0 kWh |

Auf `100` setzen, wenn an knappen Tagen gar kein Deckel gelten soll. Auf denselben Wert wie `soc_corridor_max` setzen, um die Anhebung abzuschalten.

> **Kein Netzbezug:** Ein höherer Deckel bedeutet nicht, dass die Batterie aus dem Netz geladen wird. Der Deckel ist eine Grenze, keine Aufforderung — geladen wird ausschließlich aus PV-Überschuss.

### `soc_corridor_min_scarce` (Standard: 25 %)

Untergrenze an **knappen Tagen**, symmetrisch zum angehobenen Deckel.

Eine hohe Untergrenze zwingt im Winter zu Netzbezug, sobald die Batterie sie erreicht — genau das, was vermieden werden soll. Abgesenkt wird aber **vorsichtiger als der Deckel angehoben**: Tiefentladung schadet LFP-Zellen mehr als hoher Ladestand.

| Tag | Korridor | nutzbar |
|---|---|---|
| Sommer (38 kWh Prognose) | 30–80 % | 5,3 kWh |
| Winter (21 kWh Prognose) | 25–95 % | **7,5 kWh** |

Im Winter stehen damit 2,2 kWh mehr zur Verfügung — rund vier Stunden Wärmepumpenbetrieb, die sonst aus dem Netz kämen.

`soc_hard_safety_min` bleibt in jedem Fall die harte Untergrenze: Ein niedrigerer Wert hier wird darauf begrenzt.

### `soc_hard_safety_min` (Standard: 15 %)

Notbremse. Darunter wird das **Entladen gesperrt** (Register 1040 = 0 W).

Da nie aus dem Netz geladen wird, ist das die einzig sinnvolle Reaktion auf einen kritisch tiefen SOC: die Batterie wartet auf PV, statt weiter leergezogen zu werden.

## Ladeleistungs-Drosselung

### `enable_charge_throttling` (Standard: `true`)

Verteilt die noch fehlende Energie über die verbleibenden PV-Stunden, statt vormittags mit voller Leistung zu laden.

**Beispiel:** 3,7 kWh fehlen, 10 Stunden bis Sonnenuntergang → 370 W statt 3900 W.

Zwei Effekte: niedrigere C-Rate, und der Ziel-SOC wird erst gegen Abend erreicht statt am Vormittag. Letzteres ist der wirksamste Hebel gegen langes Verweilen bei hohem SOC.

Die Rechnung läuft in **jedem** Regelzyklus neu. Ziehen Wolken auf und der SOC bleibt zurück, steigt die erlaubte Leistung automatisch — das System korrigiert sich selbst.

### `max_discharge_power` (Standard: 0)

Obergrenze für das Entladen in Watt (Register 1040). **0 bedeutet: das Limit des Wechselrichters übernehmen** — der Wert wird beim Start aus Register 1040 gelesen.

Das hat nichts mit `max_charge_power` zu tun. Frühere Versionen setzten beides auf denselben Wert und haben die Entladeleistung dadurch ohne Grund beschnitten.

Nur setzen, wenn du das Entladen bewusst drosseln willst (z. B. um Lastspitzen aus der Batterie zu begrenzen).

Im Sicherheitsfall (`soc_hard_safety_min` unterschritten) wird die Grenze unabhängig davon auf 0 W gesetzt.

### Vorrangfenster für knappe Tage

```yaml
priority_window_start: 11
priority_window_end: 15
priority_window_max_pv_kwh: 25.0   # 0 = Fenster immer aktiv
```

In diesen Stunden wird **nicht gedrosselt**, solange die Tagesprognose unter `priority_window_max_pv_kwh` liegt.

**Warum:** An kurzen Wintertagen fällt fast die gesamte Erzeugung in wenige Mittagsstunden. Was dort nicht in die Batterie geht, fehlt abends und muss aus dem Netz nachgekauft werden — zum vollen Bezugspreis, während der ungenutzte Überschuss zum kleinen Einspeisetarif weggeht. In dieser Lage ist Autarkie mehr wert als die letzte Schonung der Zellen.

An ertragreichen Tagen bleibt das Fenster inaktiv, weil die Energie ohnehin reicht und die Drosselung dann nichts kostet:

| Tag | 11:00 | 13:00 | 15:00 |
|---|---|---|---|
| Winter, 21 kWh Prognose | 4300 W | 4300 W | 4300 W |
| Sommer, 38 kWh Prognose | 684 W | 1322 W | 4300 W |

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

Zwingend sind nur **Koordinaten**; fehlen sie, bleibt die API aus. Ein Key erhöht nur das Ratelimit, die Daten sind dieselben.

**Ratelimit:** Die öffentliche Schnittstelle erlaubt **12 Abrufe pro Stunde und IP**. Das Add-on hält das ein:
- Ein Abruf liefert **alle Stundenwerte für heute und morgen** auf einmal
- Ergebnis wird **30 Minuten** zwischengespeichert → 2 Abrufe/Stunde pro Dachfläche
- Ebenen mit identischer Neigung *und* Ausrichtung werden zusammengefasst (gleiche Kurve, nur skaliert) — zwei solche Flächen kosten also nur einen Abruf
- Nach einem `HTTP 429` wird bis zum von der API genannten `retry-at` pausiert, nach Netzwerkfehlern 10 Minuten

Im Log erkennst du eine Überschreitung an:
```
Forecast.Solar Ratelimit erreicht (12 Abrufe pro 3600s). Naechster Versuch: ...
```
Das ist kein Defekt — das Add-on wartet dann selbstständig ab.

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

## Home-Assistant-Entitäten

Mit `publish_ha_sensors: true` (Standard) veröffentlicht das Add-on seinen Plan als HA-Entitäten. Der Recorder schreibt sie mit — damit bekommst du Verlauf, Diagramme und Auslöser für Automatisierungen, ohne dass das Add-on eine eigene Historie führen müsste.

| Entität | Bedeutung |
|---|---|
| `sensor.kostal_bm_target_soc` | Aktueller SOC-Deckel (%) |
| `sensor.kostal_bm_min_soc` | Aktuelle Entladegrenze (%) |
| `sensor.kostal_bm_max_charge_power` | Aktuelle Ladeleistungsgrenze (W) |
| `sensor.kostal_bm_overnight_need` | Prognostizierter Nachtbedarf (kWh) |
| `sensor.kostal_bm_tomorrow_shortfall` | Fehlbetrag morgen (kWh) |
| `sensor.kostal_bm_pv_forecast_today` | PV-Prognose heute (kWh) |
| `sensor.kostal_bm_status` | `normal`, `safety` oder `calibration` |

Der Status-Sensor trägt die **Begründung als Attribut** — im Verlauf ist damit nachvollziehbar, warum eine Entscheidung fiel, nicht nur welche. Ebenso der zurückgelesene Registerzustand und ob der Dry-Run aktiv war.

Das Präfix lässt sich über `ha_entity_prefix` ändern.

### Nützliches Diagramm für die Beobachtungsphase

```yaml
type: history-graph
hours_to_show: 72
entities:
  - sensor.deine_batterie_soc                # dein Ist-SOC-Sensor
  - sensor.kostal_bm_target_soc              # der Deckel
  - sensor.kostal_bm_min_soc                 # die Untergrenze
```

Daran siehst du direkt, ob der SOC im Korridor bleibt und ob der Deckel greift.

### Beispiel: Warnung bei blockierter Batterie

```yaml
automation:
  - alias: "Batterie blockiert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.kostal_bm_max_charge_power
        below: 1
        for: "00:10:00"
    action:
      - service: notify.persistent_notification
        data:
          message: "Ladeleistungsgrenze steht auf 0 W - Batterie moeglicherweise blockiert"
```

> **Einschränkung:** Über die REST-API angelegte Entitäten stehen nicht in der Entitäts-Registry. Nach einem HA-Neustart fehlen sie, bis das Add-on sie erneut schreibt — längstens ein `control_interval`, also 30 Sekunden. Umbenennen über die HA-Oberfläche ist nicht möglich.

## Wirkungskontrolle

Im Dashboard, Karte **📈 Wirkungskontrolle**: Wertet die SOC-Historie aus Home Assistant aus und beantwortet die Frage, ob die Strategie etwas gebracht hat.

Gemessen wird die **Verweildauer bei hohem Ladestand** — die kalendarische Alterung hängt stärker davon ab als von der Zyklenzahl.

```
VORHER  (ohne Strategie)   (10.0 Tage, 240 Messpunkte)
   Ladestand im Mittel     59.2 %   (min 15.0 / max 100.0)
   ueber 80 %              60.0 h  = 25.1 % der Zeit
   ueber 95 %              20.0 h  =  8.4 % der Zeit
   Vollzyklen              8.5  (0.85 pro Tag)

NACHHER (mit Strategie)    (10.0 Tage, 240 Messpunkte)
   ueber 80 %               0.0 h  =  0.0 % der Zeit
   ueber 95 %               0.0 h  =  0.0 % der Zeit
   Vollzyklen              4.8  (0.48 pro Tag)
```

Die Trennlinie ist der Zeitpunkt, an dem zum ersten Mal tatsächlich geschrieben wurde (`dry_run: false`). Er wird automatisch im Planerzustand vermerkt und bleibt danach unverändert, damit ein Neustart die Basis nicht verschiebt.

**Solange der Dry-Run läuft**, zeigt die Auswertung nur den aktuellen Zustand — genau die Ausgangswerte, gegen die später verglichen wird. Es lohnt sich, sie vor dem Scharfschalten einmal festzuhalten.

### Grenzen der Aussage

- **HAs Recorder hält standardmäßig nur ~10 Tage vor.** Der Vorher-Zeitraum ist damit begrenzt. Wer länger vergleichen will, sollte `recorder.purge_keep_days` erhöhen, bevor er scharf schaltet.
- Umfasst ein Zeitraum weniger als 7 Tage, weist die Auswertung selbst darauf hin, dass das Ergebnis **nicht belastbar** ist. Wetter und Verbrauch schwanken stärker als der Effekt der Strategie.
- Lücken über 3 Stunden werden aus der Zeitrechnung ausgenommen, damit Ausfälle die Anteile nicht verfälschen.
- **Keine Aussage über Geld.** Ersparnis hängt an Tarifen und Einspeisevergütung, die das Add-on nicht kennt. Hier geht es um die Batterie.

## Fehlersuche

### „Warte auf ersten Plan"

Der Plan wird im `control_interval` (Standard 30 s) berechnet. Erscheint dauerhaft nichts, prüfe:
- Ist `auto_optimization_enabled: true`?
- Läuft die Automatik (Toggle im Dashboard)?
- Liefert `battery_soc_sensor` einen Wert?

### SOC-Deckel bleibt immer bei `soc_corridor_max`

Siehe die Einschränkung oben — dein Nachtbedarf übersteigt vermutlich den nutzbaren Korridor. Prüfe im Dashboard den Wert „Nachtbedarf" gegen deine Kapazität.

### Registerdiagnose beim Start

Direkt nach dem Start protokolliert das Add-on einmalig, was es an deinem Wechselrichter vorfindet. **Das läuft auch im Dry-Run**, weil Lesen gefahrlos ist:

```
--- Registerdiagnose ---
  1068 Batteriekapazitaet : 10700 Wh (10.7 kWh) | konfiguriert: 10.7 kWh
  1080 Management-Modus    : Extern via MODBUS (Rohwert 2)
  1038 Max. Ladeleistung   : 4300.0 W
  1040 Max. Entladeleistung: 4300.0 W
  1042 Minimum SOC         : 10.0 %
  1044 Maximum SOC         : 100.0 %
  -> Limit-Register lesbar, Steuerung sollte funktionieren
------------------------
```

So liest du das:

- **Alle vier Limit-Register lesbar** → dein Wechselrichter unterstützt die Steuerung. Erscheint stattdessen `NICHT lesbar`, wird die Strategie an diesem Gerät nicht funktionieren.
- **1068 gegen `battery_capacity`**: Weicht der gemeldete Wert deutlich ab, kommt eine Warnung — alle Energieberechnungen hängen an diesem Parameter.
- **1080 Management-Modus**: rein informativ, zeigt die aktuell aktive Betriebsart.

Zusätzlich wird bei jeder Planänderung der Ist-Zustand mitgeloggt:

```
[DRY-RUN] Register-Ist-Zustand: max_charge_power=4300.0 · max_soc=100.0 · min_soc=10.0
```

Damit siehst du **vor** dem Scharfschalten, was sich ändern würde. Im Beispiel oben stünde der Wechselrichter auf 10–100 % — die Strategie würde daraus 30–80 % machen.

### Registertest: nimmt der Wechselrichter die Limits an?

Dass die Register **lesbar** sind, beweist noch nicht, dass Schreibzugriffe auch wirken. Im Dashboard gibt es dafür den Knopf **🔬 Registertest ausführen**.

Der Test schreibt je Register einen minimal veränderten Wert (z. B. Max-SOC 100 → 98 %), liest zurück und stellt den Originalwert sofort wieder her. Er schreibt **auch im Dry-Run**, weil genau das die zu klärende Frage ist — die Änderungen sind winzig und bestehen nur Sekundenbruchteile.

```
Batteriemanagement-Modus: Kein externes Batteriemanagement (Rohwert 0)
Dry-Run war aktiv: ja

  ✓ min_soc            10.0 → 12.0 gelesen: 12.0 → zurück auf 10.0
  ✓ max_soc            100.0 → 98.0 gelesen: 98.0 → zurück auf 100.0
  ✗ max_charge_power   4544.5 → 4444.5 gelesen: 4544.5 → zurück auf 4544.5

Abgelehnt: max_charge_power
```

`✓ angenommen` heißt: dieses Register wirkt. `✗ ABGELEHNT` heißt: der geschriebene Wert kam nicht an — dieser Hebel funktioniert an deinem Gerät nicht.

Der Test nennt außerdem den aktiven **Batteriemanagement-Modus**. Das ist wichtig, weil sich das Verhalten je nach Modus unterscheiden kann — führe den Test daher nach einem Moduswechsel erneut aus.

### Batteriemanagement-Modus (Register 1080) — WICHTIG

| Rohwert | Modus | SOC-Register | Leistungsregister | Timeout-Blockade |
|---|---|---|---|---|
| 0 | Intern | ❌ | ❌ | – |
| **1** | **Extern über Digital I/O** | ✅ | ✅ | keine |
| 2 | Extern über Modbus TCP | ✅ | ⚠️ | ⚠️ nach Timeout |

**Erforderlich ist Modus 1: „Extern über Digital I/O".** Einzustellen im Kostal-Webinterface unter *Service → Batterie → Batteriesteuerung*.

Das klingt zunächst falsch, ist aber richtig:

- Ohne angeschlossene Verdrahtung sind alle Digitaleingänge inaktiv. Laut der Befehlstabelle des Wechselrichters bedeutet das *„kein Externer Zugriff, interne Batteriesteuerung aktiv"* — der Wechselrichter macht also seine ganz normale Eigenverbrauchs-Optimierung.
- Gleichzeitig ist externes Batteriemanagement nominell aktiv, wodurch die Modbus-Register 1038–1044 wirken.
- Ein Timeout gibt es nicht: Digitaleingänge sind ein Dauerzustand, es kann nichts ausbleiben.

**In Modus 0 (Intern)** ignoriert der Wechselrichter alle vier Register — die Strategie hätte keinerlei Wirkung.

**In Modus 2 (Modbus TCP)** erwartet das Gerät regelmäßig Kommandos. Bleiben sie länger als das eingestellte Timeout aus, setzt die Firmware die Leistungsgrenzen auf 0 und **blockiert die Batterie vollständig**. Da diese Strategie bewusst keine Setpoints schreibt, tritt das zuverlässig ein.

### Grenzwerte persistieren

Ein geschriebener Grenzwert bleibt im Wechselrichter stehen — auch wenn das Add-on stoppt. An realer Hardware verifiziert: ein Ladelimit von 2000 W hielt über 3 Minuten ohne Nachschreiben unverändert.

Das ist einerseits gut (keine Abhängigkeit von durchgehendem Betrieb), erfordert aber Sorgfalt:

- Das Add-on schreibt **nie 0 W** als Grenzwert. Ein hängengebliebenes 0-W-Limit würde die Batterie unsichtbar dauerhaft blockieren. Das Laden wird stattdessen über den SOC-Deckel (Register 1044) gestoppt, das Entladen über die SOC-Untergrenze (1042).
- Beim geordneten Beenden setzt das Add-on alle vier Register auf die beim Start vorgefundenen Werte zurück. Danach verhält sich die Anlage wie ohne Add-on.

### Batteriemanagement-Modus im Detail

| Rohwert | Bedeutung |
|---|---|
| 0 | Kein externes Batteriemanagement (intern) |
| 1 | Extern via digital I/O |
| 2 | Extern via MODBUS |

Die `forecast`-Strategie ist für **Modus 0** entworfen: der Wechselrichter führt seine eigene Eigenverbrauchs-Optimierung aus, und die Limit-Register geben nur den Rahmen vor.

In Modus 2 erwartet das Gerät stattdessen Leistungs-Setpoints auf Register 1034 — die diese Strategie bewusst nie schreibt, weil sie nachts Netzstrom ziehen würden. Steht dein Wechselrichter auf Modus 2 (z. B. als Überbleibsel der Preisstrategie), stelle ihn im Kostal-Webinterface unter *Service → Batterie* auf interne Steuerung zurück und prüfe anschließend mit dem Registertest, ob die Limits weiterhin angenommen werden.

> Das Umschalten über das Add-on erfordert `installer_password` und `master_password` in der Konfiguration. Ohne diese geht es nur über das Webinterface.

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
