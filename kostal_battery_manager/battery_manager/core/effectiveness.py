#!/usr/bin/env python3
"""
Wirkungskontrolle (v0.12.0)

Beantwortet die Frage, die am Ende zaehlt: Hat die Strategie etwas
gebracht?

Gemessen wird an der SOC-Historie aus Home Assistant. Die entscheidende
Groesse fuer die Lebensdauer ist die VERWEILDAUER bei hohem Ladestand -
kalendarische Alterung haengt staerker davon ab als von der Zyklenzahl.

Bewusst keine Aussage ueber Geld: Ersparnis haengt an Tarifen und
Einspeiseverguetung, die das Add-on nicht kennt. Hier geht es um die
Batterie.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _parse_entry(entry: Dict):
    """
    Wandelt einen HA-Historieneintrag in (Zeitpunkt, SOC).

    Returns None, wenn der Eintrag unbrauchbar ist - 'unavailable' und
    'unknown' kommen bei Neustarts regelmaessig vor.
    """
    raw = entry.get('state')
    if raw is None or str(raw).strip().lower() in ('', 'unavailable', 'unknown'):
        return None
    try:
        soc = float(raw)
    except (ValueError, TypeError):
        return None

    stamp = entry.get('last_changed') or entry.get('last_updated')
    if not stamp:
        return None
    try:
        ts = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except ValueError:
        return None

    return ts, soc


def analyse_soc_history(history: List[Dict],
                        corridor_min: float = 30.0,
                        corridor_max: float = 80.0,
                        high_soc_threshold: float = 95.0,
                        max_gap_hours: float = 12.0) -> Optional[Dict]:
    """
    Wertet eine SOC-Historie aus.

    Args:
        history: Rohdaten aus HomeAssistantClient.get_history()
        corridor_min/max: der konfigurierte Korridor
        high_soc_threshold: ab hier gilt der Ladestand als kritisch hoch

    Returns:
        dict mit Kennzahlen, oder None bei zu wenig Daten.

    Die Zeitanteile werden ueber die Dauer ZWISCHEN den Messpunkten
    gewichtet, nicht ueber deren Anzahl - HA schreibt nur bei Aenderung,
    ein stundenlang konstanter SOC erzeugt also nur einen Eintrag.

    Genau daraus folgt `max_gap_hours`: Eine Luecke bedeutet fast immer
    KONSTANTEN SOC, nicht fehlende Daten. Und konstant hoher SOC ist der
    Zustand, den diese Auswertung messen soll - ein knapper Schwellwert
    wuerde ausgerechnet die langen Plateaus bei 100% verwerfen. Erst
    Luecken jenseits von `max_gap_hours` gelten als Ausfall.
    """
    points = [p for p in (_parse_entry(e) for e in history) if p]
    if len(points) < 2:
        return None
    points.sort(key=lambda p: p[0])

    total_h = 0.0
    above_max_h = 0.0
    above_high_h = 0.0
    below_min_h = 0.0
    weighted_soc = 0.0
    charge_sum = 0.0          # Summe der SOC-Zuwaechse -> Vollzyklen

    verworfen_h = 0.0
    for (t1, soc1), (t2, soc2) in zip(points, points[1:]):
        hours = (t2 - t1).total_seconds() / 3600.0
        if hours <= 0 or hours > max_gap_hours:
            verworfen_h += max(0.0, hours)
            if soc2 > soc1:
                charge_sum += soc2 - soc1
            continue

        total_h += hours
        weighted_soc += soc1 * hours
        if soc1 > corridor_max:
            above_max_h += hours
        if soc1 >= high_soc_threshold:
            above_high_h += hours
        if soc1 < corridor_min:
            below_min_h += hours
        if soc2 > soc1:
            charge_sum += soc2 - soc1

    if total_h <= 0:
        return None

    return {
        'von': points[0][0].isoformat(),
        'bis': points[-1][0].isoformat(),
        'messpunkte': len(points),
        'stunden_gesamt': round(total_h, 1),
        'tage': round(total_h / 24, 1),
        'soc_mittel': round(weighted_soc / total_h, 1),
        'soc_min': round(min(p[1] for p in points), 1),
        'soc_max': round(max(p[1] for p in points), 1),
        'stunden_ueber_korridor': round(above_max_h, 1),
        'anteil_ueber_korridor': round(above_max_h / total_h * 100, 1),
        'stunden_ueber_95': round(above_high_h, 1),
        'anteil_ueber_95': round(above_high_h / total_h * 100, 1),
        'stunden_unter_korridor': round(below_min_h, 1),
        'anteil_unter_korridor': round(below_min_h / total_h * 100, 1),
        'vollzyklen': round(charge_sum / 100, 2),
        'vollzyklen_pro_tag': round((charge_sum / 100) / (total_h / 24), 2) if total_h > 0 else 0,
        'verworfene_stunden': round(verworfen_h, 1),
        'max_luecke_stunden': max_gap_hours,
    }


def split_history(history: List[Dict], cutoff: datetime):
    """Teilt die Historie an einem Zeitpunkt - fuer Vorher/Nachher."""
    before, after = [], []
    for entry in history:
        parsed = _parse_entry(entry)
        if not parsed:
            continue
        (before if parsed[0] < cutoff else after).append(entry)
    return before, after


def compare(before: Optional[Dict], after: Optional[Dict]) -> Dict:
    """
    Stellt zwei Auswertungen gegenueber und formuliert ein Fazit.

    Wichtig: Ein Vergleich ueber wenige Tage sagt wenig - Wetter und
    Verbrauch schwanken staerker als der Effekt der Strategie. Deshalb
    wird die Datenbasis immer mitgenannt und bei duenner Lage gewarnt.
    """
    if not before or not after:
        return {'moeglich': False,
                'hinweis': 'Noch kein Vorher/Nachher-Vergleich moeglich - '
                           'es fehlen Daten aus einem der beiden Zeitraeume.'}

    delta = round(before['anteil_ueber_korridor'] - after['anteil_ueber_korridor'], 1)
    knapp = min(before['tage'], after['tage']) < 7

    if delta > 1:
        fazit = (f'Die Zeit ueber dem Korridor ist von {before["anteil_ueber_korridor"]}% '
                 f'auf {after["anteil_ueber_korridor"]}% gesunken ({delta} Prozentpunkte). '
                 f'Die Batterie verweilt seltener bei hohem Ladestand.')
    elif delta < -1:
        fazit = (f'Die Zeit ueber dem Korridor ist von {before["anteil_ueber_korridor"]}% '
                 f'auf {after["anteil_ueber_korridor"]}% GESTIEGEN. Das widerspricht der '
                 f'Erwartung - Konfiguration und Registerwerte pruefen.')
    else:
        fazit = 'Kein nennenswerter Unterschied messbar.'

    if knapp:
        fazit += (' ACHTUNG: Einer der Zeitraeume umfasst weniger als 7 Tage. '
                  'Wetter und Verbrauch schwanken staerker als der Effekt - '
                  'das Ergebnis ist noch nicht belastbar.')

    return {'moeglich': True, 'delta_anteil_ueber_korridor': delta,
            'belastbar': not knapp, 'fazit': fazit}
