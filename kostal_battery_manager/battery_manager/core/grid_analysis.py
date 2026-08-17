#!/usr/bin/env python3
"""
Netzbezugs-Auswertung (v0.15.0)

Schliesst die Luecke der Wirkungskontrolle: Bisher wurde nur gemessen, wie
gut es der Batterie geht - Verweildauer bei hohem Ladestand, Vollzyklen.
Das eigentliche Ziel ist aber Autarkie: moeglichst wenig Netzbezug.

Beides zusammen macht die Abwaegung erst nachpruefbar. Ein niedrigerer
SOC-Deckel schont die Zellen und kostet Autarkie; ohne diese Zahlen
bleibt offen, wie teuer die Schonung tatsaechlich war.

Zwei Datenquellen werden unterstuetzt:

  1. Ein ENERGIEZAEHLER in kWh (`total_increasing`). Bevorzugt, weil die
     Tagessumme direkt aus zwei Zaehlerstaenden folgt - unabhaengig davon,
     wie oft Home Assistant aufgezeichnet hat.

  2. Ein LEISTUNGSSENSOR in W (positiv = Bezug, negativ = Einspeisung).
     Wird ueber die Zeit integriert. Funktioniert, ist aber ungenauer:
     Der Recorder schreibt nur bei Zustandsaenderung, und eine kurze
     Lastspitze zwischen zwei Eintraegen bleibt unsichtbar.
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Fenster, das die Batterie ueberbruecken soll. Netzbezug INNERHALB dieses
# Fensters ist der aussagekraeftige Wert: Tagsueber kann auch bei voller
# Batterie Bezug entstehen, wenn die Last groesser ist als die Erzeugung -
# das sagt ueber die Strategie nichts. Nachts dagegen haette die Batterie
# liefern sollen.
NACHT_START = 20   # ab 20:00
NACHT_ENDE = 6     # bis 05:59


def _ist_nacht(stunde: int) -> bool:
    return stunde >= NACHT_START or stunde < NACHT_ENDE


def _parse(entry: Dict):
    """(Zeitpunkt, Wert) aus einem HA-Historieneintrag, oder None."""
    raw = entry.get('state')
    if raw is None or str(raw).strip().lower() in ('', 'unavailable', 'unknown'):
        return None
    try:
        wert = float(raw)
    except (ValueError, TypeError):
        return None

    stamp = entry.get('last_changed') or entry.get('last_updated')
    if not stamp:
        return None
    try:
        ts = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except ValueError:
        return None
    return ts, wert


def aus_zaehlerstand(history: List[Dict], faktor: float = 1.0
                     ) -> Dict[str, Dict[str, float]]:
    """
    Tagesverbraeuche aus einem kumulierten Zaehler.

    `faktor` rechnet die Rohwerte in kWh um - der KOSTAL Smart Energy Meter
    liefert Wh, andere Zaehler kWh. Die Einheit wird aus der Entitaet
    gelesen und nicht geraten: Ein um Faktor 1000 falscher Wert saehe
    plausibel genug aus, um lange unbemerkt zu bleiben.

    Zaehlerstaende koennen zurueckspringen - bei einem Neustart der
    Integration oder einem Geraetetausch. Ein Rueckwaertssprung wird
    verworfen statt als negativer Verbrauch gewertet.
    """
    punkte = [p for p in (_parse(e) for e in history) if p]
    if len(punkte) < 2:
        return {}
    punkte.sort(key=lambda p: p[0])

    tage = defaultdict(lambda: {'gesamt': 0.0, 'nacht': 0.0, 'tag': 0.0})
    for (t1, v1), (t2, v2) in zip(punkte, punkte[1:]):
        delta = (v2 - v1) * faktor
        if delta < 0:
            logger.debug(f"Zaehlerruecksprung bei {t2.isoformat()}: {v1} -> {v2}, verworfen")
            continue
        if delta == 0:
            continue
        datum = t1.date().isoformat()
        tage[datum]['gesamt'] += delta
        if _ist_nacht(t1.hour):
            tage[datum]['nacht'] += delta
        else:
            tage[datum]['tag'] += delta
    return dict(tage)


def aus_leistung(history: List[Dict], faktor: float = 1.0,
                 max_luecke_stunden: float = 3.0) -> Dict[str, Dict[str, float]]:
    """
    Tagesenergien aus einem Leistungssensor.

    `faktor` rechnet den Rohwert in kW um (W -> 0.001).

    Positiv gilt als Bezug, negativ als Einspeisung. Integriert wird mit
    dem Wert des JEWEILS FRUEHEREN Punktes ueber die Dauer bis zum
    naechsten - HA schreibt bei Zustandsaenderung, der Wert gilt also bis
    zur naechsten Aenderung.

    Anders als bei der SOC-Auswertung ist ein enger Luecken-Schwellwert
    hier richtig: Ein Leistungswert, der stundenlang unveraendert bleibt,
    ist bei Haushaltslast unrealistisch und deutet auf einen Ausfall hin.
    """
    punkte = [p for p in (_parse(e) for e in history) if p]
    if len(punkte) < 2:
        return {}
    punkte.sort(key=lambda p: p[0])

    tage = defaultdict(lambda: {'gesamt': 0.0, 'nacht': 0.0, 'tag': 0.0,
                                'einspeisung': 0.0})
    for (t1, w1), (t2, _) in zip(punkte, punkte[1:]):
        stunden = (t2 - t1).total_seconds() / 3600.0
        if stunden <= 0 or stunden > max_luecke_stunden:
            continue
        kwh = abs(w1) * faktor * stunden
        datum = t1.date().isoformat()
        if w1 > 0:
            tage[datum]['gesamt'] += kwh
            if _ist_nacht(t1.hour):
                tage[datum]['nacht'] += kwh
            else:
                tage[datum]['tag'] += kwh
        else:
            tage[datum]['einspeisung'] += kwh
    return dict(tage)


def zusammenfassen(tage: Dict[str, Dict[str, float]],
                   mindesttage: int = 1) -> Optional[Dict]:
    """
    Verdichtet Tageswerte zu Kennzahlen.

    Der ERSTE und LETZTE Tag werden verworfen, sobald mehr als zwei Tage
    vorliegen: Sie sind fast immer angeschnitten, und ein halber Tag
    verzerrt den Mittelwert nach unten.
    """
    if not tage:
        return None

    datumsliste = sorted(tage.keys())
    if len(datumsliste) > 2:
        datumsliste = datumsliste[1:-1]
    if len(datumsliste) < mindesttage:
        return None

    gesamt = [tage[d]['gesamt'] for d in datumsliste]
    nacht = [tage[d]['nacht'] for d in datumsliste]
    tagsueber = [tage[d]['tag'] for d in datumsliste]
    einspeisung = [tage[d].get('einspeisung', 0.0) for d in datumsliste]
    n = len(datumsliste)

    return {
        'von': datumsliste[0],
        'bis': datumsliste[-1],
        'tage': n,
        'bezug_gesamt_kwh': round(sum(gesamt), 1),
        'bezug_pro_tag_kwh': round(sum(gesamt) / n, 2),
        'bezug_nacht_pro_tag_kwh': round(sum(nacht) / n, 2),
        'bezug_tag_pro_tag_kwh': round(sum(tagsueber) / n, 2),
        'nachtanteil_prozent': round(sum(nacht) / sum(gesamt) * 100, 1) if sum(gesamt) > 0 else 0.0,
        'einspeisung_pro_tag_kwh': round(sum(einspeisung) / n, 2) if any(einspeisung) else None,
        'bester_tag_kwh': round(min(gesamt), 2),
        'schlechtester_tag_kwh': round(max(gesamt), 2),
    }


# Umrechnung der Rohwerte in kWh (Zaehler) bzw. kW (Leistung).
FAKTOR_ENERGIE = {'wh': 0.001, 'kwh': 1.0, 'mwh': 1000.0}
FAKTOR_LEISTUNG = {'w': 0.001, 'kw': 1.0}


def einheit_faktor(einheit: Optional[str], quelle: str) -> Optional[float]:
    """
    Umrechnungsfaktor aus der Einheit der Entitaet.

    Gibt None zurueck, wenn die Einheit unbekannt ist. Der Aufrufer soll
    dann abbrechen und die Einheit nennen, statt stillschweigend 1.0
    anzunehmen - ein um Faktor 1000 falscher Netzbezug faellt nicht
    zwangslaeufig auf.
    """
    tabelle = FAKTOR_ENERGIE if quelle == 'energie' else FAKTOR_LEISTUNG
    return tabelle.get((einheit or '').strip().lower())


def auswerten(history: List[Dict], quelle: str, faktor: float = 1.0) -> Optional[Dict]:
    """
    Wertet eine Historie aus. `quelle` ist 'energie' oder 'leistung'.
    """
    tage = (aus_zaehlerstand(history, faktor) if quelle == 'energie'
            else aus_leistung(history, faktor))
    ergebnis = zusammenfassen(tage)
    if ergebnis:
        ergebnis['quelle'] = quelle
    return ergebnis


def teilen(history: List[Dict], cutoff: datetime):
    """Teilt die Historie am Zeitpunkt des Scharfschaltens."""
    vorher, nachher = [], []
    for entry in history:
        p = _parse(entry)
        if not p:
            continue
        (vorher if p[0] < cutoff else nachher).append(entry)
    return vorher, nachher


def vergleichen(vorher: Optional[Dict], nachher: Optional[Dict]) -> Dict:
    """
    Stellt Netzbezug vor und nach dem Scharfschalten gegenueber.

    Bewusst ohne Geldbetrag: Der Arbeitspreis steht nicht in der
    Konfiguration, und eine erfundene Zahl waere schlechter als keine.

    Die groesste Fehlerquelle ist hier nicht die Messung, sondern das
    Wetter: Eine sonnige Woche senkt den Netzbezug staerker als jede
    Strategie. Deshalb wird bei duenner Datenlage ausdruecklich gewarnt.
    """
    if not vorher or not nachher:
        return {'moeglich': False,
                'hinweis': 'Noch kein Vorher/Nachher-Vergleich moeglich - '
                           'es fehlen Daten aus einem der beiden Zeitraeume.'}

    delta = round(nachher['bezug_pro_tag_kwh'] - vorher['bezug_pro_tag_kwh'], 2)
    delta_nacht = round(nachher['bezug_nacht_pro_tag_kwh']
                        - vorher['bezug_nacht_pro_tag_kwh'], 2)
    knapp = min(vorher['tage'], nachher['tage']) < 7

    if delta < -0.1:
        fazit = (f'Der Netzbezug ist von {vorher["bezug_pro_tag_kwh"]} auf '
                 f'{nachher["bezug_pro_tag_kwh"]} kWh pro Tag gesunken '
                 f'({abs(delta)} kWh weniger).')
    elif delta > 0.1:
        fazit = (f'Der Netzbezug ist von {vorher["bezug_pro_tag_kwh"]} auf '
                 f'{nachher["bezug_pro_tag_kwh"]} kWh pro Tag GESTIEGEN '
                 f'({delta} kWh mehr).')
    else:
        fazit = 'Der Netzbezug hat sich nicht nennenswert veraendert.'

    if delta_nacht > 0.1:
        fazit += (f' Davon entfallen {delta_nacht} kWh auf die Nachtstunden - '
                  f'dort haette die Batterie liefern sollen. Ein zu niedriger '
                  f'SOC-Deckel ist die naheliegende Ursache.')
    elif delta_nacht < -0.1:
        fazit += (f' In den Nachtstunden allein sind es {abs(delta_nacht)} kWh '
                  f'weniger - die Batterie traegt die Nacht besser als zuvor.')

    if knapp:
        fazit += (' ACHTUNG: Einer der Zeitraeume umfasst weniger als 7 Tage. '
                  'Das Wetter schwankt staerker als der Effekt der Strategie - '
                  'das Ergebnis ist noch nicht belastbar.')

    return {'moeglich': True,
            'delta_pro_tag_kwh': delta,
            'delta_nacht_pro_tag_kwh': delta_nacht,
            'belastbar': not knapp,
            'fazit': fazit}
