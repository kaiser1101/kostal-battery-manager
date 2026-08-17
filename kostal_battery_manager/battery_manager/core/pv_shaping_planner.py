#!/usr/bin/env python3
"""
PV-Shaping-Planer (v0.10.0)

Ersetzt die "Evening Top-up"-Logik, die noch davon ausging, dass abends
Netzstrom zugekauft wird. Hier wird NIE aus dem Netz geladen.

Stattdessen werden dem Wechselrichter nur GRENZEN vorgegeben
(Modbus 1038/1040/1042/1044). Seine interne Eigenverbrauchs-Optimierung
laeuft unveraendert weiter - eben nur innerhalb dieses Rahmens.

Ziel ist Batterielebensdauer:
  - Max-SOC dynamisch deckeln, wenn morgen viel PV kommt
    -> weniger Kalendarische Alterung durch Verweilen bei hohem SOC
  - Ladeleistung drosseln, damit die Ladung ueber den Nachmittag
    verteilt wird statt vormittags mit voller Leistung
    -> niedrigere C-Rate UND spaeteres Erreichen des Ziel-SOC
  - Entladegrenze schuetzen, damit keine Tiefentladung entsteht
  - Periodische Kalibrierladung auf 100%, damit die SOC-Anzeige
    des BMS nicht wegdriftet
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PVShapingPlanner:
    """Berechnet Batterie-Grenzwerte aus PV-Prognose und gelerntem Verbrauch."""

    # Unterhalb dieses Restueberschusses ist der Tag zu Ende - dann gibt es
    # nichts mehr zu verteilen und erst recht nichts zu retten.
    REST_UEBERSCHUSS_MIN_KWH = 0.5
    # Unterhalb dieses Rueckstands gilt der Ziel-SOC als erreicht. Nahe null
    # wird jeder Vergleich mit dem Rueckstand bedeutungslos.
    DEFICIT_MIN_KWH = 0.3
    # Hysterese: Aus der Knappheit heraus muss der Ueberschuss deutlicher
    # reichen als fuer den Eintritt noetig war. Sonst kippt der Modus bei
    # jedem Zehntel kWh hin und her - beobachtet als Wechsel zwischen 500 W
    # und 4300 W im Abstand von 32 Sekunden.
    KNAPPHEIT_HYSTERESE = 1.35
    # Totband fuer den SOC-Deckel. Der Wechselrichter speichert ohnehin nur
    # ganze Prozent; ohne Totband erzeugt jede Prognoseaktualisierung einen
    # Schreibvorgang, obwohl sich am Geraet nichts aendert.
    SOC_TOTBAND_PROZENT = 1.5

    def __init__(self, config: Dict, state_path: str = '/data/pv_shaping_state.json'):
        self.soc_corridor_min = config.get('soc_corridor_min', 30)
        self.soc_corridor_max = config.get('soc_corridor_max', 85)
        self.soc_hard_safety_min = config.get('soc_hard_safety_min', 15)
        self.pv_forecast_safety_margin = config.get('pv_forecast_safety_margin', 0.8)
        self.pv_dropoff_threshold = config.get('pv_dropoff_threshold', 0.05)

        self.min_charge_power = config.get('min_charge_power', 500)
        # Ab welchem Verhaeltnis Ueberschuss/Rueckstand ueberhaupt gedrosselt
        # wird. Darunter herrscht Knappheit, und Drosseln kostet nur Energie.
        self.scarcity_factor = config.get('throttle_scarcity_factor', 1.5)
        # Vorrangfenster: In diesen Stunden wird nicht gedrosselt, sobald der
        # Tag knapp ist. An kurzen Wintertagen faellt fast die gesamte
        # Erzeugung in wenige Mittagsstunden - was dort nicht in die Batterie
        # geht, fehlt abends und muss aus dem Netz kommen.
        self.priority_start = config.get('priority_window_start', 11)
        self.priority_end = config.get('priority_window_end', 15)
        # Oberhalb dieser Tagesprognose ist genug Energie da, das Fenster
        # bleibt dann inaktiv und es wird normal gedrosselt. 0 = immer aktiv.
        self.priority_max_pv = config.get('priority_window_max_pv_kwh', 25.0)
        # An knappen Tagen wird der SOC-Deckel angehoben. Begruendung:
        # Der Deckel schuetzt vor langem Verweilen bei hohem Ladestand -
        # aber im Winter wird die Batterie ohnehin jede Nacht tief entladen,
        # dieses Verweilen entsteht also gar nicht. Was der Deckel dort
        # kostet, ist stattdessen teurer Netzbezug am Abend.
        self.soc_corridor_max_scarce = config.get('soc_corridor_max_scarce',
                                                  self.soc_corridor_max)
        # Untergrenze an knappen Tagen. Symmetrisch zum Deckel: Im Winter
        # zwingt eine hohe Untergrenze zu Netzbezug, sobald die Batterie sie
        # erreicht. Tiefentladung schadet LFP-Zellen aber mehr als hoher
        # Ladestand - deshalb hier vorsichtiger absenken als beim Deckel.
        self.soc_corridor_min_scarce = config.get('soc_corridor_min_scarce',
                                                  self.soc_corridor_min)
        self.enable_charge_throttling = config.get('enable_charge_throttling', True)
        self.calibration_interval_days = config.get('calibration_interval_days', 28)
        self.calibration_min_pv_kwh = config.get('calibration_min_pv_kwh', 15.0)

        self.consumption_learner = None
        self.forecast_solar_api = None
        self.last_overnight_breakdown = []
        self._last_logged_need = None
        # Laufender Zustand fuer Hysterese und Totband. Bewusst nur im
        # Arbeitsspeicher: Nach einem Neustart soll frisch entschieden
        # werden, nicht auf Basis einer alten Lage.
        self._knappheit_aktiv = False
        self._letzter_max_soc = None
        # Zwischenspeicher der gemessenen PV-Erzeugung, gueltig fuer die
        # laufende Stunde. Vergangene Stunden aendern sich nicht mehr.
        self._pv_ist_cache = None

        self.state_path = state_path
        self._state = self._load_state()

        # Bei Erstinstallation gibt es noch kein Kalibrierdatum. Ohne
        # Startwert waere die Kalibrierung sofort faellig und die Batterie
        # wuerde ab Tag 1 taeglich auf 100% laden - genau das Gegenteil
        # des Ziels. Deshalb: Intervall ab heute rechnen.
        if 'last_calibration_date' not in self._state:
            self._state['last_calibration_date'] = datetime.now().astimezone().date().isoformat()
            self._save_state()
            logger.info(f"Kalibrier-Intervall initialisiert - erste Kalibrierladung in "
                        f"{self.calibration_interval_days} Tagen")

    # ------------------------------------------------------------------
    # Abhaengigkeiten
    # ------------------------------------------------------------------
    def mark_live(self, when=None):
        """
        Vermerkt den Zeitpunkt, ab dem tatsaechlich geschrieben wird.

        Dient als Trennlinie der Wirkungskontrolle: alles davor ist das
        Verhalten ohne Strategie, alles danach mit. Wird nur beim ersten
        Mal gesetzt, damit ein Neustart die Basis nicht verschiebt.
        """
        if self._state.get('live_since'):
            return
        self._state['live_since'] = (when or datetime.now().astimezone()).isoformat()
        self._save_state()
        logger.info(f"Scharfschaltung vermerkt: {self._state['live_since']} - "
                    f"ab hier laeuft die Wirkungskontrolle")

    def set_consumption_learner(self, learner):
        self.consumption_learner = learner
        logger.info("Consumption learner integrated into PV shaping planner")

    def set_forecast_solar_api(self, api):
        self.forecast_solar_api = api
        logger.info("Forecast.Solar API integrated into PV shaping planner")

    # ------------------------------------------------------------------
    # Persistenter Zustand (nur fuer die Kalibrierladung)
    # ------------------------------------------------------------------
    def _load_state(self) -> Dict:
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load planner state: {e}")
        return {}

    def _save_state(self):
        try:
            with open(self.state_path, 'w') as f:
                json.dump(self._state, f)
        except Exception as e:
            logger.warning(f"Could not save planner state: {e}")

    # ------------------------------------------------------------------
    # PV-Prognose
    # ------------------------------------------------------------------
    def get_hourly_pv_forecast(self, ha_client, config, for_date=None) -> Dict[int, float]:
        """Liefert {Stunde: kWh} fuer heute (for_date=None) oder ein Datum."""
        target_date = for_date or datetime.now().astimezone().date()

        if self.forecast_solar_api and config.get('enable_forecast_solar_api', False):
            planes = config.get('forecast_solar_planes', [])
            if planes:
                try:
                    # for_date durchreichen - sonst kaeme fuer "morgen" die
                    # Kurve von heute zurueck und der SOC-Deckel waere falsch.
                    hourly = self.forecast_solar_api.get_hourly_forecast(
                        planes, for_date=target_date
                    )
                    if hourly:
                        return hourly
                except Exception as e:
                    logger.error(f"Forecast.Solar API error: {e}, falling back to sensors")

        hourly_forecast = {}
        for sensor_key in ('pv_production_today_roof1', 'pv_production_today_roof2'):
            sensor = config.get(sensor_key)
            if not sensor:
                continue
            attrs = ha_client.get_attributes(sensor) if ha_client else None
            if not attrs or 'wh_hours' not in attrs:
                continue
            for ts_str, wh_value in attrs['wh_hours'].items():
                try:
                    dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    if dt.date() != target_date:
                        continue
                    hourly_forecast[dt.hour] = hourly_forecast.get(dt.hour, 0.0) + float(wh_value) / 1000.0
                except (ValueError, TypeError):
                    continue
        return hourly_forecast

    def _sunset_hour(self, pv_forecast: Dict[int, float]) -> Optional[int]:
        """Letzte Stunde, in der nennenswert PV erwartet wird."""
        if not pv_forecast:
            return None
        peak = max(pv_forecast.values())
        if peak <= 0:
            return None
        threshold = peak * self.pv_dropoff_threshold
        producing = [h for h, kwh in pv_forecast.items() if kwh >= threshold]
        return max(producing) if producing else None

    def _sunrise_hour(self, pv_forecast: Dict[int, float]) -> Optional[int]:
        """Erste Stunde, in der nennenswert PV erwartet wird."""
        if not pv_forecast:
            return None
        peak = max(pv_forecast.values())
        if peak <= 0:
            return None
        threshold = peak * self.pv_dropoff_threshold
        producing = [h for h, kwh in pv_forecast.items() if kwh >= threshold]
        return min(producing) if producing else None

    # ------------------------------------------------------------------
    # Verbrauchsprognose
    # ------------------------------------------------------------------
    def _consumption_between(self, start_dt: datetime, hours: int) -> float:
        """Summiert den gelernten Verbrauch ueber die naechsten `hours` Stunden."""
        if not self.consumption_learner or hours <= 0:
            return 0.0

        total = 0.0
        cursor = start_dt
        for _ in range(int(hours)):
            cursor = cursor + timedelta(hours=1)
            total += self.consumption_learner.get_average_consumption(
                cursor.hour, target_date=cursor.date()
            )
        return total

    def calculate_overnight_need_kwh(self, ha_client, config, now: datetime) -> float:
        """
        Verbrauch vom heutigen Sonnenuntergang bis zum morgigen
        Sonnenaufgang - die Energie, die die Batterie ueberbruecken muss.

        ACHTUNG, haeufiges Missverstaendnis: Das ist NICHT der Verbrauch der
        ruhigen Nachtstunden. Die Spanne umfasst auch die Abendspitze
        (Kochen, Licht) und die Morgenspitze (Warmwasser, Waermepumpe),
        bevor die PV wieder nennenswert liefert. Bei 13-15 Stunden Spanne
        macht das den Grossteil des Werts aus.
        """
        pv_today = self.get_hourly_pv_forecast(ha_client, config)
        pv_tomorrow = self.get_hourly_pv_forecast(
            ha_client, config, for_date=(now + timedelta(days=1)).date()
        )

        sunset = self._sunset_hour(pv_today)
        sunrise_tomorrow = self._sunrise_hour(pv_tomorrow)

        # Fallbacks, wenn keine Prognose vorliegt
        if sunset is None:
            sunset = 20
        if sunrise_tomorrow is None:
            sunrise_tomorrow = 8

        # Stunden von Sonnenuntergang bis Sonnenaufgang am Folgetag
        night_hours = (24 - sunset) + sunrise_tomorrow
        start = now.replace(hour=sunset, minute=0, second=0, microsecond=0)

        # Aufschluesselung je Stunde protokollieren. Ohne das ist nicht
        # erkennbar, ob die Prognose auf echten Messwerten beruht oder auf
        # dem pauschalen Fallback - und ein zu hoher Nachtbedarf hebt den
        # SOC-Deckel unnoetig an, womit der Hauptnutzen verloren geht.
        need = 0.0
        breakdown = []
        cursor = start
        for _ in range(night_hours):
            cursor = cursor + timedelta(hours=1)
            value = self.consumption_learner.get_average_consumption(
                cursor.hour, target_date=cursor.date()) if self.consumption_learner else 0.0
            samples = (self.consumption_learner.get_sample_count(cursor.hour)
                       if self.consumption_learner and
                          hasattr(self.consumption_learner, 'get_sample_count') else None)
            need += value
            breakdown.append({'hour': cursor.hour, 'kwh': round(value, 3), 'samples': samples})

        self.last_overnight_breakdown = breakdown
        detail = ' '.join(f"{b['hour']:02d}h={b['kwh']:.2f}" for b in breakdown)
        meldung = (f"Ueberbrueckungsbedarf {need:.2f} kWh (Sonnenuntergang {sunset}:00 -> "
                   f"Sonnenaufgang {sunrise_tomorrow}:00, {night_hours}h) | {detail}")

        # Nur bei Aenderung auf INFO. Der Wert aendert sich zweimal taeglich,
        # der Regeltakt laeuft aber alle 30 Sekunden - unveraendert geloggt
        # waeren das rund 2900 identische Zeilen pro Tag, in denen echte
        # Meldungen untergehen.
        if abs(need - (self._last_logged_need or -1)) > 0.05:
            logger.info(meldung)
            self._last_logged_need = need
        else:
            logger.debug(meldung)
        return need

    def calculate_tomorrow_shortfall_kwh(self, ha_client, config, now: datetime) -> float:
        """
        Erwarteter Fehlbetrag am Folgetag: Wenn die Prognose fuer morgen
        den Tagesverbrauch nicht deckt, muss die Batterie heute mehr
        Reserve mitnehmen.
        """
        pv_tomorrow = self.get_hourly_pv_forecast(
            ha_client, config, for_date=(now + timedelta(days=1)).date()
        )
        if not pv_tomorrow:
            # Keine Prognose = kein Vertrauen. Konservativ: kein Deckel-Rabatt.
            return None

        pv_kwh = sum(pv_tomorrow.values()) * self.pv_forecast_safety_margin

        tomorrow_start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        consumption_kwh = self._consumption_between(tomorrow_start - timedelta(hours=1), 24)

        shortfall = max(0.0, consumption_kwh - pv_kwh)
        logger.debug(f"Tomorrow: PV {pv_kwh:.1f} kWh (nach Marge) vs Verbrauch "
                     f"{consumption_kwh:.1f} kWh -> Fehlbetrag {shortfall:.1f} kWh")
        return shortfall

    # ------------------------------------------------------------------
    # Kalibrierladung
    # ------------------------------------------------------------------
    def is_calibration_due(self, ha_client, config, now: datetime) -> bool:
        """
        LFP-Zellen brauchen periodisch eine Vollladung, damit das BMS
        seine SOC-Schaetzung neu kalibrieren kann. Wir tun das nur an
        Tagen mit viel PV - dann kostet es keinen Netzstrom.
        """
        if self.calibration_interval_days <= 0:
            return False

        last = self._state.get('last_calibration_date')
        if last:
            try:
                last_date = datetime.fromisoformat(last).date()
                days_since = (now.date() - last_date).days
                if days_since < self.calibration_interval_days:
                    return False
            except ValueError:
                pass

        pv_today = self.get_hourly_pv_forecast(ha_client, config)
        pv_kwh = sum(pv_today.values()) if pv_today else 0.0
        if pv_kwh < self.calibration_min_pv_kwh:
            logger.debug(f"Kalibrierung faellig, aber PV-Prognose zu niedrig "
                         f"({pv_kwh:.1f} < {self.calibration_min_pv_kwh} kWh) - warte auf besseren Tag")
            return False

        return True

    def mark_calibration_done(self, now: datetime):
        self._state['last_calibration_date'] = now.date().isoformat()
        self._save_state()
        logger.info("Kalibrierladung abgeschlossen und vermerkt")

    # ------------------------------------------------------------------
    # Hauptberechnung
    # ------------------------------------------------------------------
    def ist_knapper_tag(self, pv_forecast: Dict[int, float]) -> bool:
        """
        Gilt ein Tag als knapp? Wird fuer heute UND fuer morgen aufgerufen.

        Gemeinsame Grundlage fuer Vorrangfenster und angehobenen SOC-Deckel,
        damit beide dieselbe Vorstellung von "knapp" haben.

        Eine leere Prognose gilt NICHT als knapp. Sonst wuerde ein Ausfall
        der Prognose-API den Deckel dauerhaft anheben - eine Fehlfunktion
        darf nicht dieselbe Wirkung haben wie ein Schlechtwettertag.
        """
        if self.priority_max_pv <= 0:
            return True
        pv_tag = sum(pv_forecast.values()) if pv_forecast else 0.0
        return 0 < pv_tag < self.priority_max_pv

    def _ist_knappheit(self, rest_ueberschuss: float, deficit_kwh: float) -> bool:
        """
        Reicht der erwartete Ueberschuss nur knapp fuer den Rueckstand?

        Mit Hysterese: Der Ausstieg aus der Knappheit verlangt einen
        deutlicheren Ueberschuss als der Einstieg. Ohne sie entscheidet ein
        Zehntel kWh ueber den gesamten Modus, und das Ladelimit springt
        zwischen Minimum und Maximum hin und her - an realer Hardware
        beobachtet als Wechsel von 500 W auf 4300 W binnen 32 Sekunden.
        """
        schwelle = deficit_kwh * self.scarcity_factor
        if self._knappheit_aktiv:
            schwelle *= self.KNAPPHEIT_HYSTERESE
        self._knappheit_aktiv = rest_ueberschuss < schwelle
        return self._knappheit_aktiv

    def _deckel_mit_totband(self, roh_max_soc: float) -> float:
        """
        Glaettet den SOC-Deckel, damit nicht jede Prognoseaktualisierung
        einen Schreibvorgang ausloest.

        Der Deckel folgt dem erwarteten Fehlbetrag fuer morgen und schwankt
        dadurch im Tagesverlauf um mehrere Prozentpunkte. Da der
        Wechselrichter nur ganze Prozent speichert, aendert ein Sprung von
        0.2 Prozentpunkten am Geraet nichts - erzeugt aber einen Schreibzugriff.
        """
        if self._letzter_max_soc is None:
            self._letzter_max_soc = roh_max_soc
        elif abs(roh_max_soc - self._letzter_max_soc) >= self.SOC_TOTBAND_PROZENT:
            self._letzter_max_soc = roh_max_soc
        return self._letzter_max_soc

    def _im_vorrangfenster(self, now: datetime, pv_today: Dict[int, float]) -> bool:
        """
        Liegt die aktuelle Stunde im Vorrangfenster eines knappen Tages?

        An kurzen Wintertagen faellt fast die gesamte Erzeugung in wenige
        Mittagsstunden. Was dort nicht gespeichert wird, fehlt abends und
        muss aus dem Netz nachgekauft werden - zum vollen Bezugspreis,
        waehrend der ungenutzte Ueberschuss zum kleinen Einspeisetarif
        weggeht. In dieser Lage ist Autarkie mehr wert als die letzte
        Schonung der Zellen.

        An ertragreichen Tagen (ueber `priority_window_max_pv_kwh`) bleibt
        das Fenster inaktiv - dort reicht die Energie ohnehin, und die
        Drosselung kostet nichts.
        """
        if not (self.priority_start <= now.hour <= self.priority_end):
            return False
        return self.ist_knapper_tag(pv_today)

    def _measured_soc_today(self, ha_client, config, now: datetime) -> Dict[int, float]:
        """
        Gemessener SOC je Stunde seit Mitternacht.

        Rein fuer die Darstellung. Faellt die Historie aus, bleibt das
        Diagramm eben ab der aktuellen Stunde leer - die Steuerung haengt
        nicht davon ab.
        """
        sensor = config.get('battery_soc_sensor')
        if not ha_client or not sensor:
            return {}
        try:
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            history = ha_client.get_history(sensor, midnight)
        except Exception as e:
            logger.debug(f"SOC-Historie fuer die Projektion nicht verfuegbar: {e}")
            return {}

        per_hour = {}
        for entry in history or []:
            raw = entry.get('state')
            if raw is None or str(raw).strip().lower() in ('', 'unavailable', 'unknown'):
                continue
            stamp = entry.get('last_changed') or entry.get('last_updated')
            if not stamp:
                continue
            try:
                ts = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
                value = float(raw)
            except (ValueError, TypeError):
                continue
            # Letzter Wert der Stunde gewinnt
            per_hour[ts.astimezone(now.tzinfo).hour] = value

        # Luecken schliessen. Bleibt der SOC konstant - etwa stundenlang bei
        # 100% - schreibt HA keine Zustandsaenderung, und diese Stunden
        # haetten gar keinen Wert. Im Diagramm entstuenden Loecher genau
        # dort, wo der Ladestand am interessantesten ist.
        if per_hour:
            letzter = None
            for hour in range(0, now.hour + 1):
                if hour in per_hour:
                    letzter = per_hour[hour]
                elif letzter is not None:
                    per_hour[hour] = letzter
        return per_hour

    def _gemessene_pv_heute(self, ha_client, config,
                            now: datetime) -> Dict[int, float]:
        """
        Tatsaechlich erzeugte PV-Energie je Stunde seit Mitternacht, in kWh.

        Quelle sind die DC-Strangleistungen des Wechselrichters
        (`pv_power_now_roof1/2`) - echte Messwerte, im Gegensatz zur
        Prognose. Beide Straenge werden addiert.

        Integriert wird mit dem Wert des jeweils FRUEHEREN Punktes ueber
        die Dauer bis zum naechsten: Home Assistant schreibt bei
        Zustandsaenderung, der Wert gilt also bis zur naechsten Aenderung.
        Luecken ueber 1 h gelten als Ausfall und werden verworfen - eine
        Leistung, die stundenlang unveraendert bleibt, gibt es bei PV
        nicht.

        Rein fuer die Darstellung. Faellt es aus, bleibt die Kurve leer.
        """
        if not ha_client:
            return {}

        # Einmal pro Stunde genuegt. Die Abfrage ist die mit Abstand
        # teuerste im Diagramm: Ein Leistungssensor im Sekundentakt liefert
        # fuer einen Tag mehrere tausend Eintraege, und es sind zwei
        # Straenge. Ohne diesen Zwischenspeicher liefe das bei jedem
        # Seitenaufruf und zusaetzlich alle fuenf Minuten.
        cache_schluessel = (now.date(), now.hour)
        if self._pv_ist_cache and self._pv_ist_cache[0] == cache_schluessel:
            return self._pv_ist_cache[1]

        mitternacht = now.replace(hour=0, minute=0, second=0, microsecond=0)
        je_stunde: Dict[int, float] = {}

        for schluessel in ('pv_power_now_roof1', 'pv_power_now_roof2'):
            sensor = (config.get(schluessel) or '').strip()
            if not sensor:
                continue
            try:
                attrs = ha_client.get_attributes(sensor) or {}
                einheit = (attrs.get('unit_of_measurement') or 'W').strip().lower()
                faktor = {'w': 0.001, 'kw': 1.0}.get(einheit)
                if faktor is None:
                    logger.warning(f"{sensor}: unbekannte Einheit '{einheit}' - "
                                   f"Ist-Erzeugung wird uebersprungen")
                    continue

                history = ha_client.get_history(sensor, mitternacht, now,
                                                no_attributes=True)
                punkte = []
                for eintrag in history or []:
                    roh = eintrag.get('state')
                    if roh is None or str(roh).strip().lower() in ('', 'unavailable', 'unknown'):
                        continue
                    stempel = eintrag.get('last_changed') or eintrag.get('last_updated')
                    if not stempel:
                        continue
                    try:
                        ts = datetime.fromisoformat(str(stempel).replace('Z', '+00:00'))
                        punkte.append((ts.astimezone(now.tzinfo), float(roh)))
                    except (ValueError, TypeError):
                        continue

                punkte.sort(key=lambda p: p[0])
                for (t1, w1), (t2, _) in zip(punkte, punkte[1:]):
                    stunden = (t2 - t1).total_seconds() / 3600.0
                    if stunden <= 0 or stunden > 1.0 or w1 <= 0:
                        continue
                    je_stunde[t1.hour] = je_stunde.get(t1.hour, 0.0) + w1 * faktor * stunden
            except Exception as e:
                logger.debug(f"Ist-Erzeugung aus {sensor} nicht verfuegbar: {e}")

        self._pv_ist_cache = (cache_schluessel, je_stunde)
        return je_stunde

    def _project_tomorrow(self, ha_client, config, current_soc, battery_capacity,
                          now: datetime, plan: Dict) -> Dict:
        """
        Projiziert den morgigen Tag von 0 bis 23 Uhr.

        Der SOC wird zunaechst ueber die Restnacht fortgeschrieben, damit
        der Startwert um Mitternacht stimmt.
        """
        pv_today = self.get_hourly_pv_forecast(ha_client, config)
        morgen = (now + timedelta(days=1)).date()
        pv_morgen = self.get_hourly_pv_forecast(ha_client, config, for_date=morgen)

        max_soc = plan['max_soc']
        min_soc = plan['min_soc']
        max_charge_kwh = plan['max_charge_power'] / 1000.0
        soc = current_soc

        def verbrauch(hour, tag):
            if not self.consumption_learner:
                return 0.0
            return self.consumption_learner.get_average_consumption(hour, target_date=tag)

        # Restnacht bis Mitternacht durchrechnen
        for hour in range(now.hour + 1, 24):
            bilanz = pv_today.get(hour, 0.0) - verbrauch(hour, now.date())
            if bilanz < 0:
                verfuegbar = max(0.0, (soc - min_soc) / 100 * battery_capacity)
                soc -= min(-bilanz, verfuegbar) / battery_capacity * 100

        hourly_soc = [None] * 24
        hourly_charging = [None] * 24
        for hour in range(24):
            bilanz = pv_morgen.get(hour, 0.0) - verbrauch(hour, morgen)
            if bilanz > 0:
                platz = max(0.0, (max_soc - soc) / 100 * battery_capacity)
                geladen = min(bilanz, max_charge_kwh, platz)
                soc += geladen / battery_capacity * 100
                hourly_charging[hour] = round(geladen, 2)
            else:
                verfuegbar = max(0.0, (soc - min_soc) / 100 * battery_capacity)
                entnommen = min(-bilanz, verfuegbar)
                soc -= entnommen / battery_capacity * 100
                hourly_charging[hour] = round(-entnommen, 2)
            hourly_soc[hour] = round(soc, 1)

        werte = [v for v in hourly_soc if v is not None]
        geladen_gesamt = sum(c for c in hourly_charging if c and c > 0)

        return {
            'success': True,
            'strategie': 'forecast',
            'fuer_morgen': True,
            'datum': morgen.isoformat(),
            'hourly_soc': hourly_soc,
            'hourly_charging': hourly_charging,
            'corridor_min': min_soc,
            'corridor_max': max_soc,
            'min_soc_reached': round(min(werte), 1) if werte else None,
            'max_soc_reached': round(max(werte), 1) if werte else None,
            'total_charging_kwh': round(geladen_gesamt, 2),
            'ab_stunde': 0,
        }

    # ------------------------------------------------------------------
    # Tagesprojektion fuer das Dashboard
    # ------------------------------------------------------------------
    def project_day(self, ha_client, config, current_soc: float,
                    battery_capacity: float, now: Optional[datetime] = None) -> Dict:
        """
        Schaetzt den SOC-Verlauf des heutigen Tages, Stunde fuer Stunde.

        Reine Vorschau fuer das Dashboard - steuert nichts. Fuer bereits
        vergangene Stunden gibt es keine Rueckrechnung; sie bleiben leer,
        damit nichts vorgetaeuscht wird, was nicht gemessen wurde.

        Bilanz je Stunde: PV-Prognose minus gelernter Verbrauch. Ueberschuss
        laedt die Batterie (begrenzt durch Ladeleistung und SOC-Deckel),
        Fehlbetrag entlaedt sie (begrenzt durch die SOC-Untergrenze).

        Returns:
            dict mit hourly_soc, hourly_charging (je 24 Werte, None fuer
            vergangene Stunden) und Kennzahlen.
        """
        now = now or datetime.now().astimezone()
        plan = self.plan(ha_client, config, current_soc, battery_capacity, now=now)

        pv_today = self.get_hourly_pv_forecast(ha_client, config)

        # Ist die PV-Zeit des Tages vorbei, zeigt eine Projektion der
        # Reststunden nichts Brauchbares mehr - es kommt ohnehin keine
        # Ladung mehr. Abends interessiert der morgige Tag.
        sunset = self._sunset_hour(pv_today)
        fuer_morgen = sunset is not None and now.hour > sunset
        if fuer_morgen:
            return self._project_tomorrow(ha_client, config, current_soc,
                                          battery_capacity, now, plan)
        max_soc = plan['max_soc']
        min_soc = plan['min_soc']
        max_charge_kwh = plan['max_charge_power'] / 1000.0

        hourly_soc = [None] * 24
        hourly_charging = [None] * 24

        # Vergangene Stunden mit GEMESSENEN Werten fuellen, sofern die
        # Historie vorliegt. Sonst zeigte das Diagramm abends fast nichts,
        # weil die Projektion erst ab der aktuellen Stunde beginnt.
        measured = self._measured_soc_today(ha_client, config, now)
        for hour, value in measured.items():
            if hour < now.hour:
                hourly_soc[hour] = round(value, 1)

        soc = current_soc
        hourly_soc[now.hour] = round(soc, 1)
        hourly_charging[now.hour] = 0.0

        for hour in range(now.hour + 1, 24):
            pv = pv_today.get(hour, 0.0)
            use = (self.consumption_learner.get_average_consumption(hour, target_date=now.date())
                   if self.consumption_learner else 0.0)
            balance = pv - use

            if balance > 0:
                # Laden, begrenzt durch Ladeleistung und Deckel
                room_kwh = max(0.0, (max_soc - soc) / 100 * battery_capacity)
                charged = min(balance, max_charge_kwh, room_kwh)
                soc += charged / battery_capacity * 100
                hourly_charging[hour] = round(charged, 2)
            else:
                # Entladen, begrenzt durch die Untergrenze
                available_kwh = max(0.0, (soc - min_soc) / 100 * battery_capacity)
                drawn = min(-balance, available_kwh)
                soc -= drawn / battery_capacity * 100
                hourly_charging[hour] = round(-drawn, 2)

            hourly_soc[hour] = round(soc, 1)

        werte = [v for v in hourly_soc if v is not None]
        geladen = sum(c for c in hourly_charging if c and c > 0)

        return {
            'success': True,
            'strategie': 'forecast',
            'hourly_soc': hourly_soc,
            'hourly_charging': hourly_charging,
            'corridor_min': min_soc,
            'corridor_max': max_soc,
            'min_soc_reached': round(min(werte), 1) if werte else None,
            'max_soc_reached': round(max(werte), 1) if werte else None,
            'total_charging_kwh': round(geladen, 2),
            'ab_stunde': now.hour,
        }

    # ------------------------------------------------------------------
    # 48-Stunden-Uebersicht fuer das Dashboard
    # ------------------------------------------------------------------
    def project_overview(self, ha_client, config, current_soc: float,
                         battery_capacity: float,
                         now: Optional[datetime] = None) -> Dict:
        """
        Heute und morgen in einer einzigen Zeitreihe, 48 Stundenwerte.

        Fuer vergangene Stunden werden GEMESSENE Werte gezeigt, ab der
        aktuellen Stunde die Projektion. Die Grenze steht in `jetzt_index`,
        damit das Diagramm beides optisch trennen kann - sonst sieht eine
        Vorhersage aus wie eine Messung.

        Alle Energiewerte sind kWh pro Stunde. Das ist zahlengleich mit der
        mittleren Leistung in kW, weshalb PV, Verbrauch und Batteriefluss
        auf einer gemeinsamen kW-Achse liegen koennen.

        Der Batteriefluss der Vergangenheit wird aus den SOC-Spruengen
        abgeleitet (dSOC x Kapazitaet) statt aus einem Leistungssensor:
        Es ist dieselbe Groesse in derselben Einheit wie die Projektion,
        und es braucht keinen zusaetzlichen Sensor.
        """
        now = now or datetime.now().astimezone()
        plan = self.plan(ha_client, config, current_soc, battery_capacity, now=now)

        heute = now.date()
        morgen = (now + timedelta(days=1)).date()
        pv_tage = {
            0: self.get_hourly_pv_forecast(ha_client, config) or {},
            1: self.get_hourly_pv_forecast(ha_client, config, for_date=morgen) or {},
        }

        max_soc = plan['max_soc']
        min_soc = plan['min_soc']
        jetzt = now.hour

        # Die Drosselgrenze gilt nur fuer HEUTE. Sie wird aus dem aktuellen
        # Rueckstand und der heute noch erwarteten Sonne berechnet - fuer
        # morgen hat sie keine Aussagekraft, weil sie dort aus den Werten
        # des naechsten Tages neu entsteht. Fuer morgen daher die volle
        # konfigurierte Ladeleistung annehmen.
        max_charge_kwh_tag = {
            0: plan['max_charge_power'] / 1000.0,
            1: float(config.get('max_charge_power', 4300)) / 1000.0,
        }

        def gelernt(hour, datum):
            if not self.consumption_learner:
                return 0.0
            return self.consumption_learner.get_average_consumption(hour, target_date=datum)

        gemessener_verbrauch = {}
        if self.consumption_learner:
            try:
                gemessener_verbrauch = self.consumption_learner.get_today_consumption(heute) or {}
            except Exception as e:
                logger.debug(f"Gemessener Verbrauch nicht verfuegbar: {e}")

        soc_gemessen = self._measured_soc_today(ha_client, config, now)
        pv_gemessen = self._gemessene_pv_heute(ha_client, config, now)

        pv = [None] * 48
        pv_ist = [None] * 48
        verbrauch = [None] * 48
        soc_reihe = [None] * 48
        batterie = [None] * 48

        # --- Vergangenheit: gemessen ----------------------------------
        for hour in range(min(jetzt, 24)):
            pv[hour] = round(pv_tage[0].get(hour, 0.0), 3)
            # Die AKTUELLE Stunde bleibt aus der Ist-Kurve heraus: Sie ist
            # noch nicht zu Ende und saehe als Einbruch aus, der keiner ist.
            if hour in pv_gemessen:
                pv_ist[hour] = round(pv_gemessen[hour], 3)
            gemessen = gemessener_verbrauch.get(hour)
            verbrauch[hour] = round(gemessen if gemessen is not None
                                    else gelernt(hour, heute), 3)
            if hour in soc_gemessen:
                soc_reihe[hour] = round(soc_gemessen[hour], 1)

        # Batteriefluss aus den SOC-Spruengen. Nur dort, wo beide
        # Nachbarwerte gemessen sind - sonst entstuende aus einer Luecke
        # ein Sprung, der wie eine Ladung aussieht.
        for hour in range(1, min(jetzt, 24)):
            vorher, jetzt_wert = soc_reihe[hour - 1], soc_reihe[hour]
            if vorher is not None and jetzt_wert is not None:
                batterie[hour] = round((jetzt_wert - vorher) / 100 * battery_capacity, 2)

        # --- Gegenwart und Zukunft: projiziert ------------------------
        soc = current_soc
        if jetzt < 24:
            soc_reihe[jetzt] = round(soc, 1)
            pv[jetzt] = round(pv_tage[0].get(jetzt, 0.0), 3)
            verbrauch[jetzt] = round(gelernt(jetzt, heute), 3)
            batterie[jetzt] = 0.0

        for idx in range(jetzt + 1, 48):
            tag, hour = divmod(idx, 24)
            datum = heute if tag == 0 else morgen

            pv_h = pv_tage[tag].get(hour, 0.0)
            use = gelernt(hour, datum)
            bilanz = pv_h - use

            if bilanz > 0:
                platz = max(0.0, (max_soc - soc) / 100 * battery_capacity)
                fluss = min(bilanz, max_charge_kwh_tag[tag], platz)
                soc += fluss / battery_capacity * 100
            else:
                verfuegbar = max(0.0, (soc - min_soc) / 100 * battery_capacity)
                fluss = -min(-bilanz, verfuegbar)
                soc += fluss / battery_capacity * 100

            pv[idx] = round(pv_h, 3)
            verbrauch[idx] = round(use, 3)
            soc_reihe[idx] = round(soc, 1)
            batterie[idx] = round(fluss, 2)

        geladen_heute = sum(b for b in batterie[:24] if b and b > 0)
        geladen_morgen = sum(b for b in batterie[24:] if b and b > 0)

        return {
            'success': True,
            'strategie': 'forecast',
            'jetzt_index': jetzt,
            'datum_heute': heute.isoformat(),
            'datum_morgen': morgen.isoformat(),
            'pv': pv,
            'pv_ist': pv_ist,
            'verbrauch': verbrauch,
            'soc': soc_reihe,
            'batterie': batterie,
            'corridor_min': min_soc,
            'corridor_max': max_soc,
            'max_charge_kw': round(max_charge_kwh_tag[0], 2),
            'pv_heute_kwh': round(sum(pv_tage[0].values()), 1),
            'pv_ist_heute_kwh': round(sum(v for v in pv_ist if v), 2),
            'pv_ist_verfuegbar': any(v is not None for v in pv_ist),
            'pv_morgen_kwh': round(sum(pv_tage[1].values()), 1),
            'verbrauch_heute_kwh': round(sum(v for v in verbrauch[:24] if v), 1),
            'verbrauch_morgen_kwh': round(sum(v for v in verbrauch[24:] if v), 1),
            'geladen_heute_kwh': round(geladen_heute, 1),
            'geladen_morgen_kwh': round(geladen_morgen, 1),
            'modus': plan['mode'],
            'begruendung': plan['reason'],
            # `pv` ist durchgehend Prognose, `pv_ist` die gemessene
            # Erzeugung aus den DC-Straengen - nur fuer vergangene Stunden.
            'pv_ist_prognose': True,
        }

    def plan(self, ha_client, config, current_soc: float, battery_capacity: float,
             now: Optional[datetime] = None) -> Dict:
        """
        Berechnet die Grenzwerte fuer den aktuellen Zeitpunkt.

        Args:
            now: Zeitpunkt der Planung. Default = jetzt. Injizierbar,
                 damit Szenarien testbar sind.

        Returns:
            dict mit max_soc, min_soc, max_charge_power, max_discharge_power,
            reason und diagnostischen Zwischenwerten.
        """
        now = now or datetime.now().astimezone()
        configured_max_power = float(config.get('max_charge_power', 3900))

        # Die Entladegrenze hat mit der Ladeleistung nichts zu tun. Wird sie
        # nicht ausdruecklich konfiguriert, uebernehmen wir das Limit des
        # Wechselrichters (Register 1040, beim Start gelesen) - sonst wuerden
        # wir seine Entladeleistung ohne Grund beschneiden.
        discharge_limit = (float(config.get('max_discharge_power') or 0)
                           or float(config.get('_hardware_max_discharge_power') or 0)
                           or configured_max_power)

        plan = {
            'timestamp': now.isoformat(),
            'current_soc': current_soc,
            'max_soc': float(self.soc_corridor_max),
            'min_soc': float(self.soc_corridor_min),
            'max_charge_power': configured_max_power,
            'max_discharge_power': discharge_limit,
            'mode': 'normal',
            'reason': '',
            'diagnostics': {},
        }

        # --- 1. Harte Notbremse ---------------------------------------
        # Ohne Netzladung koennen wir bei tiefem SOC nicht nachladen.
        # Die einzig sinnvolle Reaktion ist: Entladen stoppen und auf
        # PV warten.
        if current_soc < self.soc_hard_safety_min:
            # Entladen wird ueber die SOC-Untergrenze gestoppt, NICHT ueber
            # ein 0-W-Entladelimit. Beides wirkt gleich, aber der Grenzwert
            # persistiert: bliebe 0 W nach einem Absturz stehen, koennte die
            # Batterie nie wieder entladen. Ein hoher min_soc ist dagegen
            # harmlos und wird vom naechsten Zyklus normal korrigiert.
            plan.update({
                'mode': 'safety',
                'max_soc': 100.0,
                'min_soc': round(max(current_soc, float(self.soc_hard_safety_min)), 1),
                'max_charge_power': configured_max_power,
                'max_discharge_power': discharge_limit,
                'reason': (f'SICHERHEIT: SOC {current_soc:.1f}% unter Hartgrenze '
                           f'{self.soc_hard_safety_min}% - Entladen ueber SOC-Grenze '
                           f'gestoppt, Laden aus PV freigegeben'),
            })
            return plan

        # --- 2. Kalibrierladung ---------------------------------------
        if self.is_calibration_due(ha_client, config, now):
            plan.update({
                'mode': 'calibration',
                'max_soc': 100.0,
                'min_soc': float(self.soc_corridor_min),
                'max_charge_power': configured_max_power,
                'reason': (f'Kalibrierladung faellig (alle {self.calibration_interval_days} Tage) '
                           f'und PV-Prognose ausreichend - Ladung auf 100% freigegeben'),
            })
            if current_soc >= 99.0:
                self.mark_calibration_done(now)
                plan['reason'] += ' | 100% erreicht, Kalibrierung vermerkt'
            return plan

        # --- 3. Dynamischer SOC-Deckel --------------------------------
        overnight_kwh = self.calculate_overnight_need_kwh(ha_client, config, now)
        shortfall_kwh = self.calculate_tomorrow_shortfall_kwh(ha_client, config, now)

        if shortfall_kwh is None:
            # Ohne Prognose fuer morgen bleiben wir beim Korridor-Maximum.
            reserve_kwh = overnight_kwh
            target_soc = self.soc_corridor_max
            cap_reason = 'keine Prognose fuer morgen - Korridor-Maximum'
        else:
            reserve_kwh = overnight_kwh + shortfall_kwh
            # SOC, der diese Reserve zusaetzlich zur Entladegrenze traegt
            target_soc = self.soc_corridor_min + (reserve_kwh / battery_capacity) * 100
            if shortfall_kwh <= 0:
                cap_reason = (f'morgen deckt PV den Verbrauch - nur Ueberbrueckung '
                              f'{overnight_kwh:.1f} kWh noetig')
            else:
                cap_reason = (f'morgen fehlen {shortfall_kwh:.1f} kWh - Reserve '
                              f'{reserve_kwh:.1f} kWh noetig')

        # An knappen Tagen gilt die angehobene Obergrenze.
        #
        # "Knapp" heisst hier HEUTE ODER MORGEN. Beide Faelle brauchen
        # dieselbe Anhebung, aber aus verschiedenen Gruenden:
        #
        #   heute knapp  - die Batterie wird ohnehin jede Nacht tief
        #                  entladen. Das lange Verweilen bei hohem SOC,
        #                  vor dem der Deckel schuetzt, entsteht gar nicht.
        #
        #   morgen knapp - die Reserve fuer morgen passt nicht mehr unter
        #                  den normalen Deckel. Ohne Anhebung kappt der
        #                  Deckel die Rechnung, und was fehlt, kommt morgen
        #                  abends aus dem Netz - ausgerechnet vor einem
        #                  Schlechtwettertag, an dem nichts nachgeladen
        #                  werden kann.
        #
        # Die Anhebung erzwingt kein Vollladen: `target_soc` bleibt die
        # bindende Groesse, die Obergrenze hoert nur auf zu kappen.
        pv_today_fuer_deckel = self.get_hourly_pv_forecast(ha_client, config)
        pv_morgen_fuer_deckel = self.get_hourly_pv_forecast(
            ha_client, config, for_date=(now + timedelta(days=1)).date()
        )
        knapp_heute = self.ist_knapper_tag(pv_today_fuer_deckel)
        knapp_morgen = self.ist_knapper_tag(pv_morgen_fuer_deckel)
        knapp = knapp_heute or knapp_morgen

        obergrenze = self.soc_corridor_max_scarce if knapp else self.soc_corridor_max

        # Nur vermerken, wenn die Anhebung tatsaechlich etwas aendert. Liegt
        # der Bedarf ohnehin unter dem normalen Deckel, waere "auf 95%
        # angehoben" im Log irrefuehrend - der Deckel steht dann trotzdem
        # beim Rechenwert.
        if (knapp and obergrenze > self.soc_corridor_max
                and target_soc > self.soc_corridor_max):
            if knapp_heute:
                anlass = f'heute knapp ({sum(pv_today_fuer_deckel.values()):.1f} kWh)'
            else:
                anlass = f'morgen knapp ({sum(pv_morgen_fuer_deckel.values()):.1f} kWh)'
            cap_reason += (f'; {anlass} - Deckel von {self.soc_corridor_max:.0f}% '
                           f'auf {obergrenze:.0f}% angehoben')

        roh_max_soc = max(self.soc_corridor_min + 5.0, min(obergrenze, target_soc))
        max_soc = self._deckel_mit_totband(roh_max_soc)

        # --- 4. Entladegrenze -----------------------------------------
        # An knappen Tagen tiefer entladen duerfen, aber nie unter die
        # harte Notbremse.
        #
        # Bewusst nur `knapp_heute`, nicht `knapp_morgen`: Die Untergrenze
        # regelt, wie tief HEUTE NACHT entladen wird. Ist erst morgen
        # schlecht, bringt eine tiefere Entladung heute nacht nichts - der
        # Bezugspreis ist derselbe, egal wann gekauft wird, es bliebe also
        # nur der tiefere Zyklus. Morgen senkt die Bewertung des naechsten
        # Tages die Grenze dann selbst.
        if knapp_heute and self.soc_corridor_min_scarce < self.soc_corridor_min:
            min_soc = float(max(self.soc_corridor_min_scarce, self.soc_hard_safety_min))
            cap_reason += (f'; Untergrenze auf {min_soc:.0f}% gesenkt '
                           f'(weniger Netzbezug in der Nacht)')
        else:
            min_soc = float(self.soc_corridor_min)

        # --- 5. Ladeleistung drosseln ---------------------------------
        # Die noch fehlende Energie ueber die verbleibenden PV-Stunden
        # verteilen. Das senkt die C-Rate UND verschiebt das Erreichen
        # des Ziel-SOC nach hinten, statt vormittags voll durchzuladen.
        max_charge_power = configured_max_power
        throttle_reason = 'volle Ladeleistung'

        pv_today = self.get_hourly_pv_forecast(ha_client, config)
        sunset = self._sunset_hour(pv_today)
        sunrise = self._sunrise_hour(pv_today)

        if sunset is None or sunrise is None:
            throttle_reason = 'keine PV-Prognose - volle Ladeleistung'

        elif now.hour < sunrise or now.hour > sunset:
            # Ausserhalb der PV-Stunden bleibt die volle Ladeleistung stehen.
            #
            # Frueher wurde hier 0 W gesetzt, um Netzladung zu sperren. Das
            # ist aus zwei Gruenden falsch: Netzladung entsteht nur ueber
            # Setpoints (Register 1034), die diese Strategie nie schreibt -
            # die Sperre schuetzt also vor nichts. Und ein geschriebener
            # Grenzwert PERSISTIERT: faellt das Add-on nachts aus, bliebe die
            # Batterie dauerhaft vom Laden gesperrt.
            max_charge_power = configured_max_power
            throttle_reason = 'ausserhalb der PV-Stunden - keine Begrenzung noetig'

        elif self.enable_charge_throttling:
            # Aktuelle Stunde zaehlt mit, deshalb +1
            hours_left = max(1, sunset - now.hour + 1)
            deficit_kwh = max(0.0, (max_soc - current_soc) / 100 * battery_capacity)

            # Erwarteter Restueberschuss bis Sonnenuntergang. Nur wenn davon
            # deutlich mehr da ist als gebraucht wird, ist Drosseln ueberhaupt
            # sinnvoll - sonst verteilt man Knappheit.
            rest_ueberschuss = 0.0
            stunden_ueberschuss = {}
            for h in range(now.hour, sunset + 1):
                verbrauch = (self.consumption_learner.get_average_consumption(h, target_date=now.date())
                             if self.consumption_learner else 0.0)
                u = max(0.0, pv_today.get(h, 0.0) - verbrauch)
                stunden_ueberschuss[h] = u
                rest_ueberschuss += u

            if deficit_kwh <= self.DEFICIT_MIN_KWH:
                # Praktisch am Ziel. Nicht 0 schreiben: der Wert persistiert,
                # und der SOC-Deckel (Register 1044) stoppt das Laden ohnehin
                # zuverlaessig. Ein haengengebliebenes 0-W-Limit waere dagegen
                # unsichtbar und wuerde die Batterie dauerhaft blockieren.
                #
                # Die Schwelle ist nicht 0, sondern DEFICIT_MIN_KWH: Direkt am
                # Ziel schwankt der Rueckstand um wenige Zehntel, und bei
                # einem Rueckstand nahe null wird jeder Vergleich mit ihm
                # bedeutungslos - genau daraus entstand frueher ein Wechsel
                # zwischen 500 W und voller Leistung im Sekundenabstand.
                self._knappheit_aktiv = False
                max_charge_power = float(self.min_charge_power)
                throttle_reason = (f'Ziel-SOC {max_soc:.1f}% erreicht - '
                                   f'Deckel stoppt das Laden')
            elif self._im_vorrangfenster(now, pv_today):
                pv_tag = sum(pv_today.values())
                max_charge_power = configured_max_power
                throttle_reason = (f'Vorrangfenster {self.priority_start}-{self.priority_end} Uhr '
                                   f'bei knapper Tagesprognose ({pv_tag:.1f} kWh) - '
                                   f'volle Ladeleistung, damit abends weniger Netzbezug noetig ist')

            elif rest_ueberschuss < self.REST_UEBERSCHUSS_MIN_KWH:
                # Der Tag ist vorbei - es kommt kaum noch Sonne.
                #
                # Ohne diese Pruefung schlug die Knappheitserkennung JEDEN
                # Abend an: Gegen Sonnenuntergang geht der Restueberschuss
                # zwangslaeufig gegen null, und damit ist "Ueberschuss kleiner
                # als Rueckstand" praktisch immer erfuellt. Die Regel konnte
                # "knapper Tag" nicht von "Tag zu Ende" unterscheiden und gab
                # abends die volle Ladeleistung frei. Liegt die Prognose dann
                # zu niedrig - was am Abend regelmaessig vorkommt - laedt die
                # Batterie mit voller Leistung, obwohl nichts zu retten war.
                self._knappheit_aktiv = False
                max_charge_power = float(self.min_charge_power)
                throttle_reason = (f'Tagesende: nur noch {rest_ueberschuss:.1f} kWh '
                                   f'Ueberschuss erwartet - nichts mehr zu verteilen')

            elif (self.ist_knapper_tag(pv_today)
                  and self._ist_knappheit(rest_ueberschuss, deficit_kwh)):
                # Knappheit: Der erwartete Ueberschuss reicht kaum fuer den
                # Rueckstand. Jede gedrosselte Kilowattstunde ist endgueltig
                # verloren - besonders an sonnigen Wintertagen, wo die
                # Erzeugung in wenigen Mittagsstunden anfaellt.
                #
                # Entscheidend ist die Bindung an `ist_knapper_tag`: Der
                # Restueberschuss schrumpft im Tagesverlauf zwangslaeufig,
                # also war das Verhaeltnis Ueberschuss/Rueckstand ab dem
                # spaeten Nachmittag AUCH an 38-kWh-Sonnentagen erfuellt.
                # Die Regel loeste damit taeglich aus, obwohl sie fuer kurze
                # Wintertage gedacht ist. An ertragreichen Tagen genuegt die
                # anteilige Verteilung: Liegt der Speicher zurueck, waechst
                # der erlaubte Anteil dort von selbst.
                max_charge_power = configured_max_power
                throttle_reason = (f'knapper Tag, keine Drosselung: erwarteter Ueberschuss '
                                   f'{rest_ueberschuss:.1f} kWh deckt den Rueckstand '
                                   f'{deficit_kwh:.1f} kWh nur knapp')
            else:
                # Rueckstand PROPORTIONAL zur erwarteten Sonne verteilen, nicht
                # gleichmaessig ueber die Stunden. Die verbleibenden Stunden
                # sind unterschiedlich viel wert: mittags kommen 5 kW, abends
                # 0.5 kW. Gleichmaessige Verteilung liesse die Mittagsspitze
                # ungenutzt und koennte sie spaeter nicht nachholen.
                anteil = (stunden_ueberschuss.get(now.hour, 0.0) / rest_ueberschuss
                          if rest_ueberschuss > 0 else 1.0 / hours_left)
                erlaubt_kwh = deficit_kwh * anteil
                max_charge_power = min(configured_max_power,
                                       max(self.min_charge_power, erlaubt_kwh * 1000))
                throttle_reason = (f'{deficit_kwh:.1f} kWh nach Prognose verteilt '
                                   f'({anteil*100:.0f}% der Restsonne faellt in diese Stunde)')

        plan.update({
            'max_soc': round(max_soc, 1),
            'min_soc': round(min_soc, 1),
            'max_charge_power': round(max_charge_power, 0),
            'max_discharge_power': discharge_limit,
            'reason': f'Deckel {max_soc:.1f}% ({cap_reason}); {throttle_reason}',
            'diagnostics': {
                'overnight_need_kwh': round(overnight_kwh, 2),
                'tomorrow_shortfall_kwh': round(shortfall_kwh, 2) if shortfall_kwh is not None else None,
                'sunset_hour': sunset,
                'pv_today_kwh': round(sum(pv_today.values()), 2) if pv_today else 0.0,
                'pv_tomorrow_kwh': (round(sum(pv_morgen_fuer_deckel.values()), 2)
                                    if pv_morgen_fuer_deckel else 0.0),
                'knapp_heute': knapp_heute,
                'knapp_morgen': knapp_morgen,
                'soc_obergrenze': round(obergrenze, 1),
                'soc_deckel_roh': round(roh_max_soc, 1),
                'knappheit_aktiv': self._knappheit_aktiv,
                'overnight_breakdown': self.last_overnight_breakdown,
            },
        })
        return plan
