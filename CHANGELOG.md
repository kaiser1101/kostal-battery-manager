# Changelog

## [0.17.3] - 2026-08-21

### Fixed
- **Kein Netzbezug wurde als Fehler gemeldet.** Liefert die Historie eines
  Bezugszaehlers genau einen Eintrag, hat sich der Zaehler im Zeitraum
  nicht bewegt - Home Assistant zeichnet nur Aenderungen auf. Bei einem
  Bezugszaehler ist das kein Fehler, sondern das Ziel: Es wurde nichts
  bezogen. Die Meldung fragte stattdessen nach "unavailable".

  An realer Anlage: 3 Tage, ein einziger Zaehlerstand bei 285,10 kWh, und
  ein Ladestand, der nie unter 42 % fiel. Die Batterie hat die Naechte
  vollstaendig getragen.

  Die Meldung sagt das jetzt so und nennt die Gegenprobe: Verlauf der
  Entitaet oeffnen - eine waagrechte Linie bestaetigt es, gar keine
  Anzeige heisst Recorder-Ausschluss.

## [0.17.2] - 2026-08-21

### Fixed
- **Die Netzbezug-Meldung nannte die falsche Ursache.** Kam keine
  verwertbare Tagessumme zustande, stand dort pauschal "Zu wenige
  verwertbare Tage" - obwohl das nur eine von drei Moeglichkeiten war und
  ausgerechnet die, die sich von aussen nicht pruefen laesst. Die Meldung
  nennt jetzt die tatsaechlichen Zahlen und unterscheidet:
  Zaehler steht unveraendert (falscher Sensor oder keine Aktualisierung),
  zu wenige Eintraege mit Zahlenwert (Sensor meist "unavailable"),
  oder wirklich zu kurze Historie.

## [0.17.1] - 2026-08-21

### Fixed
- **Das Entscheidungsprotokoll war nicht aufrufbar.** Der Endpunkt
  `/api/decision_log` liess sich ueber die Ingress-Adresse nicht von Hand
  erreichen: `https://<host>/<slug>` ist die Seitenleisten-Seite, die das
  Add-on in einem Rahmen laedt - was man dort anhaengt, kommt beim Add-on
  nie an. Ein Endpunkt ohne Bedienelement ist fuer den Nutzer nicht
  vorhanden. Die Karte "Langzeit" hat jetzt den Knopf
  **Entscheidungen 30 Tage**.

## [0.17.0] - 2026-08-21

### Added
- **Entscheidungsprotokoll.** Die Steuerung schreibt mit, was sie an
  welchem Tag entschieden hat: Deckel (Spanne und Anzahl der Wechsel),
  Untergrenze, Ladegrenze, SOC-Spanne, und wie viele Zyklen auf welche
  Regel entfielen - dazu die Eingangsgroessen als Rohwerte
  (PV-Prognose heute und morgen, Ueberbrueckungsbedarf, Fehlbetrag).
  Abrufbar unter `/api/decision_log?days=30`.

  Anlass: Von den Groessen, die eine Entscheidung im Nachhinein
  beurteilbar machen, liegen drei ohnehin in Home Assistant -
  SOC-Verlauf, Netzbezug, gemessene PV. Was fehlte, war ausgerechnet
  das, was die Steuerung selbst entschieden hat. Das stand nur im Log
  und wurde ueberschrieben. In der Woche vom 17.-21.08. wurde deshalb
  fuenfmal geraten statt nachgeschlagen.

  Bewusst **ohne Bewertung**: Welche Urteilsregel taugt ("war die
  Reserve noetig?"), laesst sich erst an gesammelten Daten sehen. Die
  Auswertung kann jederzeit rueckwirkend darueber laufen - ein nicht
  aufgezeichneter Tag ist dagegen endgueltig verloren.

  Aufbewahrung 120 Tage, rund 60 kB. Gespeichert wird alle fuenf Minuten
  und immer beim Tageswechsel, damit ein abgeschlossener Tag nicht an
  einem Neustart haengenbleibt.
- Stabiler Regelschluessel `throttle_regel` im Plan ('ziel_erreicht',
  'vorrangfenster', 'tagesende', 'knappheit', 'verteilt',
  'ausserhalb_pv', 'keine_prognose', 'voll'). Damit muss die spaetere
  Auswertung keinen Log-Text zerlegen.

## [0.16.1] - 2026-08-17

### Fixed
- **Logflut bei leerer Verbrauchsdatenbank.** Ein einziger Diagrammabruf
  erzeugte 72 Warnungen in derselben Sekunde - 24 Stunden mal heute,
  morgen und Profil. Waehrend eines Home-Assistant-Neustarts begrub das
  jede andere Meldung. Der Rueckfall auf den Standardwert wird jetzt
  hoechstens alle zehn Minuten je Stunde gemeldet, und die Meldung ist
  auf Deutsch wie der Rest.

## [0.16.0] - 2026-08-17

### Added
- **Netzbezug in der Wirkungskontrolle.** Bisher wurde nur gemessen, wie
  es der Batterie geht - das eigentliche Ziel, moeglichst wenig Strom
  zuzukaufen, war nicht messbar. Neue Optionen
  `grid_import_energy_sensor`, `grid_export_energy_sensor`,
  `grid_power_sensor`. Ausgewiesen wird kWh pro Tag, getrennt nach Nacht
  (20-06 Uhr) und Tag, mit Vorher/Nachher am Scharfschalten.
  Die Einheit wird aus der Entitaet gelesen (Wh/kWh/MWh bzw. W/kW), nicht
  angenommen - der Unterschied ist Faktor 1000 und faellt in Tageswerten
  nicht sicher auf.
- **Gelernte Standortkorrektur der PV-Prognose.** Nach Sonnenuntergang
  werden Tagesprognose und gemessene Erzeugung verglichen; aus mindestens
  fuenf Tagen entsteht ein Korrekturfaktor (Median, begrenzt auf
  0,6 bis 1,6), mit dem die Prognose skaliert wird.
  Anlass war der 17.08.: Die Prognose meldete abends 0,2 kWh Restsonne,
  die Anlage lieferte noch rund 4 kW - die Steuerung glaubte der Prognose
  und gab die volle Ladeleistung frei.
- **Batteriealterung.** Die nutzbare Kapazitaet aus Register 1068 wird
  monatlich mitgeschrieben. Ueber Jahre ergibt das eine echte
  Degradationskurve - die einzige Zahl, die am Ende beantwortet, ob sich
  die Schonung gelohnt hat.
- Neue Karte "Langzeit" im Dashboard und Endpunkt `/api/battery_health`.

### Changed
- `get_hourly_pv_forecast()` liefert die Prognose jetzt korrigiert; mit
  `roh=True` unveraendert. Gelernt wird ausschliesslich gegen den
  Rohwert, sonst naehme die Korrektur sich selbst als Messgrundlage.
- Median statt Mittelwert, Mindestdatenlage und Deckelung: Lieber die
  ungeschoente Prognose als eine Korrektur aus zwei Zufallstagen.

## [0.15.4] - 2026-08-17

### Fixed
- **Das Diagramm lud spuerbar langsamer.** Die in v0.15.3 ergaenzte
  Ist-Kurve holte bei JEDEM Aufruf die vollstaendige Tageshistorie beider
  DC-Straenge. Leistungssensoren aktualisieren im Sekundentakt: gemessen
  am eigenen Log lieferte ein Sensor fuer eine Stunde 327 Eintraege, also
  rund 7.800 pro Tag - mal zwei Straenge etwa 15.700 Eintraege statt
  zuvor 50, bei jedem Seitenaufruf und zusaetzlich alle fuenf Minuten.
  Die Messwerte werden jetzt fuer die laufende Stunde zwischengespeichert;
  vergangene Stunden aendern sich ohnehin nicht mehr. Statt 24 Abrufen
  pro Stunde bleiben zwei.
- Die Abfrage laeuft zusaetzlich mit `no_attributes`. Bei Sensoren im
  Sekundentakt machen die wiederholten Attribute (friendly_name, unit,
  device_class) den groessten Teil der Antwort aus.

## [0.15.3] - 2026-08-17

### Added
- **Tatsaechliche PV-Erzeugung im Diagramm**, als eigene Kurve neben der
  Prognose. Quelle sind die DC-Strangleistungen des Wechselrichters
  (`pv_power_now_roof1/2`), stundenweise integriert.
  Durchgezogen = gemessen, gestrichelt = Prognose. Die Prognosekurve ist
  jetzt durchgehend gestrichelt, auch rueckwirkend - sie war nie eine
  Messung.
  Damit wird sichtbar, ob Forecast.Solar am eigenen Standort systematisch
  danebenliegt. Genau diese Luecke hatte am 17.08. die volle Ladeleistung
  am Abend ausgeloest: Die Prognose meldete 0,2 kWh Restsonne, die Anlage
  lieferte noch rund 4 kW.
- Die Kopfzeile zeigt die gemessene Tageserzeugung, sobald sie vorliegt,
  sonst weiterhin die Prognose - jeweils benannt.

### Changed
- Die Ist-Kurve endet an der aktuellen Stunde. Die laufende Stunde ist
  noch nicht zu Ende und saehe als Einbruch aus, der keiner ist.
- Luecken ueber 1 h in der Leistungshistorie gelten als Ausfall: Eine
  PV-Leistung, die stundenlang unveraendert bleibt, gibt es nicht.

## [0.15.2] - 2026-08-17

### Fixed
- **Die Verbrauchskurve blieb brettflach bei 0,83 kWh/h.** Nicht der
  Rueckfallwert war die Ursache, sondern die Gewichtung: Importierte
  Werte (168 Datensaetze = 7 Tage) und gemessene Werte (1-2 Tage) wurden
  gemittelt, und der Import gewann schlicht durch Menge. Sichtbar als
  flache Linie ueber den ganzen Tag - mit kleinen Dellen nur in den
  wenigen Stunden, fuer die schon gemessen wurde.
  Gemessene Werte verdraengen jetzt importierte, statt sich mit ihnen zu
  mitteln.
- **Der Wochentagsfilter blockierte die Messwerte zusaetzlich.** Wer
  gerade erst anfaengt zu lernen, hat Daten fuer ein bis zwei Wochentage;
  wird zuerst nach Wochentag gefiltert, bleiben fuer fast jede Stunde nur
  importierte Werte uebrig. Die QUELLE kommt jetzt vor dem WOCHENTAG:
  gemessen/gleicher Tag -> gemessen/irgendein Tag -> importiert/gleicher
  Tag -> importiert/irgendein Tag -> Standardwert.
- `get_hourly_profile()` fuellte Luecken mit dem Durchschnitt ueber die
  vorhandenen STUNDEN - also einem flachen Tageswert, gleichermassen fuer
  3 Uhr nachts wie fuer 19 Uhr. Dieselbe Ursache war in
  `get_average_consumption` laengst behoben, hier nicht. Die Funktion
  greift jetzt direkt darauf zurueck, damit beide nicht wieder
  auseinanderlaufen koennen.

## [0.15.1] - 2026-08-17

### Changed
- **Diagramm auf den Stand von v0.14.0 zurueckgenommen.** Die in v0.15.0
  ergaenzte Ist-Kurve der PV-Erzeugung ist wieder entfernt.

### Fixed
- Die Fehlermeldung der Wirkungskontrolle legte sich darauf fest, die
  Entitaet sei "wahrscheinlich vom Recorder ausgeschlossen". Sie nennt
  jetzt auch die wahrscheinlichere Ursache: eine umbenannte Entitaet,
  deren aeltere Historie unter dem alten Namen liegt.

### Zurueckgenommen
- Die in v0.15.1 zunaechst eingebaute Normalisierung der Zeitstempel in
  `get_history()` ist wieder entfernt. Sie beruhte auf der Annahme, ein
  fehlender Zeitzonen-Offset lasse die History-API leer antworten - das
  Log widerlegt es: Im selben Lauf lieferte ein naiver Zeitstempel fuer
  `home_power` 327 Eintraege und fuer `battery_soc` nichts. Der
  Unterschied liegt an der Entitaet, nicht am Format.

## [0.15.0] - 2026-08-17

### Fixed
- **Die Drosselung schaltete sich jeden Abend ab.** Die Knappheitsregel
  ("Ueberschuss deckt den Rueckstand nur knapp -> volle Ladeleistung")
  war fuer kurze Wintertage gedacht, hing aber nur am Verhaeltnis
  Restueberschuss/Rueckstand. Gegen Sonnenuntergang geht der
  Restueberschuss zwangslaeufig gegen null - damit war die Bedingung
  taeglich erfuellt, auch an 38-kWh-Sonnentagen.
  An realer Hardware beobachtet: von 14:54 bis 17:26 durchgehend 500 W,
  ab 17:31 dann 4300 W. Liegt die Prognose abends zu niedrig - was
  regelmaessig vorkommt - laedt die Batterie dann mit voller Leistung.
  Die Regel ist jetzt an `ist_knapper_tag` gebunden.
- **Neue Abbruchbedingung "Tagesende":** Unter 0,5 kWh erwartetem
  Restueberschuss gibt es nichts mehr zu verteilen und erst recht nichts
  zu retten - die Grenze bleibt unten.
- **Rueckstand nahe null.** Direkt am Ziel-SOC schwankt der Rueckstand um
  wenige Zehntel, und jeder Vergleich mit ihm wird bedeutungslos. Ab
  jetzt gilt der Ziel-SOC unterhalb von 0,3 kWh Rueckstand als erreicht.
- **Flattern zwischen 500 W und 4300 W im Sekundenabstand** (im Log:
  17:47:00 -> 500 W, 17:47:32 -> 4300 W). Der Wechsel in die Knappheit
  hat jetzt eine Hysterese von 35 %.
- **Schreibzugriffe bei jedem Zehntel.** Der SOC-Deckel folgt dem
  erwarteten Fehlbetrag fuer morgen und wanderte im Log zwischen 73,0 %
  und 83,6 % - jede Aenderung ein Schreibvorgang, obwohl der
  Wechselrichter nur ganze Prozent speichert. Jetzt mit Totband
  (1,5 Prozentpunkte) und Schreibtoleranz (50 W / 0,5 %).

### Added
- **Tatsaechliche PV-Erzeugung im Diagramm**, neben der Prognose. Quelle
  sind die DC-Strangleistungen des Wechselrichters
  (`pv_power_now_roof1/2`), stundenweise integriert. Durchgezogen =
  gemessen, gestrichelt = Prognose. Damit ist sichtbar, ob
  Forecast.Solar am eigenen Standort systematisch danebenliegt - genau
  die Ursache, die den abendlichen Volllastfall ausgeloest hat.
- Diagnosewerte `soc_deckel_roh` und `knappheit_aktiv`, damit Totband und
  Hysterese nichts verbergen.

## [0.14.0] - 2026-08-16

### Added
- **Eine gemeinsame Tagesuebersicht** loest die getrennten Diagramme
  "Batterie-Prognose" und "Prognostizierter Verbrauch" ab. PV, Verbrauch,
  Batteriefluss und Ladestand liegen jetzt uebereinander in einer
  Zeitreihe ueber 48 Stunden - heute und morgen.
  Die Groessen haengen zusammen: Wieviel geladen wird, folgt aus PV minus
  Verbrauch. Nebeneinander war dieser Zusammenhang nicht zu sehen.
- PV, Verbrauch und Batteriefluss teilen sich EINE kW-Achse. Die Werte
  sind kWh pro Stunde, und das ist zahlengleich mit der mittleren
  Leistung - eine Umrechnung war nie noetig, nur eine gemeinsame Achse.
- **Durchgezogen = gemessen, gestrichelt = Prognose**, dazu eine rote
  Jetzt-Linie und die Trennung zwischen heute und morgen. Ohne diese
  Unterscheidung sieht eine Rechnung aus wie eine Messung.
- Der erlaubte SOC-Korridor wird als Band hinterlegt - damit ist auf einen
  Blick sichtbar, ob der Ladestand an eine Grenze stoesst.
- Neuer Endpunkt `/api/overview_chart` und `PVShapingPlanner.project_overview()`.

### Changed
- Der Batteriefluss der Vergangenheit wird aus den SOC-Spruengen
  abgeleitet (dSOC x Kapazitaet) statt aus einem Leistungssensor: dieselbe
  Groesse in derselben Einheit wie die Projektion, ohne zusaetzlichen
  Sensor. Luecken in der Historie erzeugen bewusst keinen Balken.
- Die Karte ist hell gehalten, abweichend vom uebrigen Dashboard. Vier
  Reihen ueber 48 Stunden brauchen Kontrast, den der dunkle Hintergrund
  nicht hergibt.

### Fixed
- Die Projektion fuer MORGEN verwendete die heutige Drosselgrenze. Die
  wird aus dem heutigen Rueckstand und der heute noch erwarteten Sonne
  berechnet und hat fuer morgen keine Aussagekraft - der Folgetag wurde
  dadurch zu pessimistisch dargestellt (Beispiel: 4,5 statt 6,1 kWh
  Ladung). Fuer morgen gilt jetzt die volle konfigurierte Ladeleistung.

## [0.13.6] - 2026-08-16

### Added
- **Knappheitserkennung beruecksichtigt jetzt auch den Folgetag.** Bisher
  wurde der angehobene SOC-Deckel (`soc_corridor_max_scarce`) nur
  ausgeloest, wenn HEUTE knapp war. Der teure Fall war damit nicht
  abgedeckt: heute sonnig, morgen truebe. Der Planer rechnete den
  Fehlbetrag fuer morgen zwar korrekt in die Reserve ein, der normale
  Deckel kappte das Ergebnis aber wieder - und was fehlte, kam morgen
  abends aus dem Netz, ausgerechnet an einem Tag ohne Nachlademöglichkeit.
  Beispiel (10,7 kWh, heute 38 kWh / morgen 12 kWh Prognose):
  Deckel vorher 85 %, jetzt 95 %.
- Diagnosewerte `knapp_heute`, `knapp_morgen`, `pv_tomorrow_kwh` und
  `soc_obergrenze` im Plan - damit ist im Nachhinein nachvollziehbar,
  welcher der beiden Tage die Anhebung ausgeloest hat.

### Changed
- Die **Untergrenze** (`soc_corridor_min_scarce`) haengt bewusst weiterhin
  nur am heutigen Tag. Sie regelt, wie tief heute Nacht entladen wird; ist
  erst morgen schlecht, brachte eine tiefere Entladung heute nacht nur
  einen tieferen Zyklus - der Bezugspreis ist derselbe, egal wann gekauft
  wird.
- Die Anhebung wird nur noch protokolliert, wenn sie tatsaechlich etwas
  aendert. Zuvor stand "Deckel auf 95% angehoben" auch dann im Log, wenn
  der Deckel wegen niedrigen Bedarfs bei 82,6 % blieb.
- Eine **leere Prognose gilt nicht als knapp**. Ein Ausfall der
  Prognose-API darf nicht dieselbe Wirkung haben wie ein
  Schlechtwettertag.

## [0.13.5] - 2026-08-16

### Changed
- **`soc_corridor_max` Standard von 80 auf 85 % angehoben.** Bei 80 % war
  die Kappung an der Referenzanlage die *bindende* Grenze, nicht mehr die
  Sicherheitsobergrenze: Bei 10,7 kWh Kapazitaet und 5,63 kWh
  Ueberbrueckungsbedarf rechnet der Planer einen Ziel-SOC von 82,6 % aus
  und wurde auf 80 % gekappt. Es fehlten rund 0,28 kWh pro Nacht, die
  morgens aus dem Netz kamen - genau das, was die Strategie vermeiden
  soll.
  85 % laesst die Rechnung entscheiden statt die Kappung; der dynamische
  Deckel liegt an den meisten Tagen weiterhin deutlich darunter. Auf die
  Verweildauer ueber 95 % hat die Aenderung keinen Einfluss.

### Added
- CONFIGURATION.md: Rechenweg, mit dem jeder seinen eigenen
  `soc_corridor_max` bestimmen kann, statt eine Pauschalempfehlung zu
  uebernehmen. Der Wert haengt am Verhaeltnis von Nachtverbrauch zu
  Speichergroesse und ist damit anlagenspezifisch.

### Fixed
- Die Erklaerung zu `soc_corridor_max` beruhte noch auf dem fehlerhaften
  Verbrauchslerner (9,1 kWh Nachtbedarf) und riet deshalb dazu, den Deckel
  zu *senken*. Mit korrekt gelerntem Verbrauch ist die Schlussfolgerung
  genau umgekehrt.

## [0.13.4] - 2026-08-16

### Changed
- **Dokumentation auf den Stand von v0.13.3 gebracht.** README beschrieb
  noch die in v0.11.0 entfernte Nachtsperre, nannte die Betriebsart falsch
  und kannte weder saisonalen Korridor, Vorrangfenster,
  Knappheitserkennung, HA-Entitaeten noch Wirkungskontrolle.
- **Zielsetzung klargestellt:** Das Ziel ist Autarkie - der Speicher soll
  durch die Sonne so weit gefuellt werden, dass abends kein Netzstrom
  gekauft werden muss. Die Schonung der Batterie nimmt nur heraus, was
  ueber den tatsaechlichen Bedarf hinaus gespeichert wuerde. "Nicht vom
  Netz laden" ist die Technik dahinter, nicht der Zweck.
- Die Zusage zur Drosselung explizit dokumentiert: Gedrosselt wird nur bei
  nachweislichem Ueberschuss (`throttle_scarcity_factor`), die Drosselung
  kann den Speicher also nicht abends leeren.

### Fixed
- CONFIGURATION.md empfahl fuer die `forecast`-Strategie **Modus 0
  (intern)**. Das ist falsch - in Modus 0 ignoriert der Wechselrichter
  alle vier Limit-Register. Korrekt ist Modus 1 ("Extern ueber Digital
  I/O") ohne verdrahtete Eingaenge. An realer Hardware verifiziert.
- Der Abschnitt "Nachtsperre" beschrieb ein seit v0.11.0 entferntes
  Verhalten. Ergaenzt um die Begruendung: Grenzwerte bleiben im
  Wechselrichter stehen, ein haengengebliebenes 0-W-Limit haette die
  Batterie dauerhaft blockiert.

## [0.13.3] - 2026-08-16

### Added
- **Abgesenkte Entladegrenze an knappen Tagen**
  (`soc_corridor_min_scarce`, Standard 25%), symmetrisch zum angehobenen
  Deckel. Eine hohe Untergrenze zwingt im Winter zu Netzbezug, sobald die
  Batterie sie erreicht. Abgesenkt wird vorsichtiger als der Deckel
  angehoben, weil Tiefentladung LFP-Zellen mehr schadet als hoher
  Ladestand.
  Sommer 30-80% (5.3 kWh nutzbar), Winter 25-95% (7.5 kWh).
  `soc_hard_safety_min` bleibt in jedem Fall die harte Untergrenze.

## [0.13.2] - 2026-08-16

### Added
- **Angehobener SOC-Deckel an knappen Tagen** (`soc_corridor_max_scarce`,
  Standard 95%). Der Deckel schuetzt vor langem Verweilen bei hohem
  Ladestand - im Winter wird die Batterie aber ohnehin jede Nacht tief
  entladen, dieses Verweilen entsteht dort gar nicht. Was der Deckel dann
  kostet, ist teurer Netzbezug am Abend.
  Sommer 30-80% (5.3 kWh nutzbar), Winter 30-95% (7.0 kWh nutzbar).

### Changed
- Vorrangfenster und angehobener Deckel nutzen jetzt dieselbe
  Knappheitsdefinition (`ist_knapper_tag`), damit beide dasselbe unter
  "knapp" verstehen.

## [0.13.1] - 2026-08-16

### Added
- **Vorrangfenster fuer knappe Tage** (`priority_window_start`/`_end`,
  Standard 11-15 Uhr): In diesen Stunden wird nicht gedrosselt, solange die
  Tagesprognose unter `priority_window_max_pv_kwh` (Standard 25 kWh) liegt.
  An kurzen Wintertagen faellt fast die gesamte Erzeugung in wenige
  Mittagsstunden. Was dort nicht gespeichert wird, muss abends zum vollen
  Bezugspreis nachgekauft werden, waehrend der ungenutzte Ueberschuss zum
  kleinen Einspeisetarif weggeht. Autarkie geht dann vor Schonung.
  An ertragreichen Tagen bleibt das Fenster inaktiv.

## [0.13.0] - 2026-08-16

### Fixed
- **Drosselung verteilte gleichmaessig ueber die Stunden statt nach
  Sonnenprognose.** Die verbleibenden Stunden sind unterschiedlich viel
  wert: mittags kommen 5 kW, abends 0.5 kW. Die gleichmaessige Verteilung
  liess die Mittagsspitze ungenutzt und konnte sie danach nicht nachholen -
  eine sich selbst verstaerkende Falle, weil der Rueckstand gross blieb und
  das Limit nur langsam mitstieg.
  An einem sonnigen Wintertag mit 5-kW-Spitze: SOC endete bei 71% statt 80%,
  7 kWh Ueberschuss blieben ungenutzt - vor einer 15-Stunden-Nacht.
  Der Rueckstand wird jetzt proportional zur erwarteten Sonne verteilt.

### Added
- **Knappheitserkennung** (`throttle_scarcity_factor`, Standard 1.5):
  Deckt der erwartete Restueberschuss den Rueckstand nur knapp, wird gar
  nicht gedrosselt. Drosseln ergibt nur Sinn, wenn MEHR Ueberschuss da ist
  als gebraucht wird - sonst verteilt man Knappheit und verliert Energie
  endgueltig.

## [0.12.9] - 2026-08-16

### Fixed
- **Freigabe beim Beenden stellte die Ladeleistung nicht wieder her.**
  Uebergeben wurde `max_charge_power` aus der Konfiguration statt des beim
  Start vorgefundenen Geraetewerts. Nach dem Beenden blieb dadurch eine
  Begrenzung stehen, die niemand gesetzt hatte - an realer Hardware 4300 W
  statt der ~4450 W des Wechselrichters. Die SOC-Register wurden korrekt
  zurueckgesetzt, nur die Leistung nicht.

## [0.12.8] - 2026-08-16

### Added
- **Positive Bestaetigung der Registeruebernahme.** Im Scharfbetrieb wurde
  die Rueckmeldung bisher nur bei Abweichung geloggt - der Erfolgsfall war
  Schweigen, und gerade beim ersten scharfen Schreibvorgang musste man die
  Abwesenheit einer Warnung deuten. Jetzt meldet das Add-on
  `Wechselrichter bestaetigt: SOC-Korridor 30.0-80.0%, laden max 500.0W`,
  und zwar nur bei Aenderung, damit die 10-Minuten-Auffrischung das Log
  nicht flutet.

## [0.12.7] - 2026-08-16

### Fixed
- **Die Wirkungskontrolle verwarf ausgerechnet das, was sie messen soll.**
  Luecken ueber 3 Stunden galten als Ausfall und flogen aus der
  Zeitrechnung. Bei konstantem SOC schreibt Home Assistant aber gar keine
  Zustandsaenderung - lange Plateaus bei 100% erzeugen also genau solche
  Luecken. Die Verweildauer bei hohem Ladestand wurde dadurch systematisch
  zu niedrig ausgewiesen.
  Die Grenze liegt jetzt bei 12 Stunden, und die verworfene Zeit wird
  ausgewiesen, statt stillschweigend zu verschwinden.
  An einem Testfall mit 6h-Plateau: Anteil ueber 95% steigt von 31.6% auf
  43.5%.

## [0.12.6] - 2026-08-16

### Fixed
- **Log-Flut durch den Ueberbrueckungsbedarf.** Die Zeile samt stundenweiser
  Aufschluesselung wurde in JEDEM Regelzyklus geschrieben - alle 30
  Sekunden, rund 2900 identische Zeilen pro Tag, obwohl sich der Wert nur
  zweimal taeglich aendert. Echte Meldungen gingen darin unter. Jetzt auf
  INFO nur bei Aenderung, sonst DEBUG.

## [0.12.5] - 2026-08-15

### Fixed
- **Luecken im Prognosediagramm.** Bleibt der SOC konstant - etwa
  stundenlang bei 100% - schreibt Home Assistant keine Zustandsaenderung.
  Diese Stunden hatten gar keinen Messwert, und im Diagramm entstand ein
  Loch genau dort, wo der Ladestand am interessantesten ist. Der letzte
  bekannte Wert wird jetzt fortgeschrieben.
- **Abends zeigte die Projektion nichts Brauchbares.** Sie deckte nur die
  Reststunden des Tages ab; nach Sonnenuntergang also nur noch Entladung
  und "Ladung 0 kWh". Ist die PV-Zeit vorbei, wird jetzt der MORGIGE Tag
  projiziert - dann steht dort, was tatsaechlich geplant ist.
- Die Zusammenfassung unter dem Diagramm nennt jetzt, ob heute oder morgen
  gezeigt wird und bis wann gemessen statt projiziert wurde.

## [0.12.4] - 2026-08-15

### Fixed
- **Wirkungskontrolle scheiterte bei kurzer Historie.** Angeboten wurden
  nur 30 und 90 Tage; reicht die Aufzeichnung erst wenige Tage zurueck -
  etwa direkt nach einer Aenderung von `purge_keep_days` - lieferten beide
  nichts, obwohl Daten vorhanden waren. Der Zeitraum wird jetzt
  automatisch verkuerzt (30 -> 14 -> 7 -> 3 -> 2 Tage) und der
  tatsaechlich ausgewertete Zeitraum ausgewiesen. Zusaetzlich ein
  7-Tage-Knopf.
- Die Balken im Prognosediagramm hiessen "Geplante Ladung", zeigen aber
  auch die Entladung als negativen Wert. Jetzt "Ladung (+) / Entladung
  (-) pro Stunde".

## [0.12.3] - 2026-08-15

### Fixed
- **Timeout-Handler war in der falschen Methode gelandet.** Ein
  fehlplatzierter `except requests.Timeout` in `set_state()` haette dort
  eine leere Liste statt `False` zurueckgegeben und auf ein Attribut
  zugegriffen, das die Methode nicht kennt. Verschoben nach
  `get_history()`, wo er hingehoert.

### Added
- `HomeAssistantClient.last_history_error`: haelt die Ursache eines
  fehlgeschlagenen Historienabrufs fest (HTTP-Status, leere Antwort,
  Zeitueberschreitung). Die Wirkungskontrolle nennt sie jetzt im Klartext,
  statt eine Vermutung auszugeben.

## [0.12.2] - 2026-08-15

### Fixed
- **Diagramm "Batterie-Prognose" blieb leer.** Seit v0.10.4 liefert
  `/api/battery_schedule` in der forecast-Strategie keine Daten mehr, weil
  der preisbasierte Zweig dort abgeschaltet ist. Das Diagramm fiel auf
  Nullwerte zurueck. Jetzt liefert der Planer eine eigene Tagesprojektion.
- Die Wirkungskontrolle meldete pauschal "Keine Historie ... Recorder haelt
  nur 10 Tage vor". Jetzt wird unterschieden, ob die Entitaet gar nicht
  existiert, ob nur der Zeitraum zu lang war, oder ob die Entitaet vom
  Recorder ausgeschlossen ist.

### Added
- **Tagesprojektion** (`PVShapingPlanner.project_day()`): schaetzt den
  SOC-Verlauf stundenweise aus PV-Prognose und gelerntem Verbrauch,
  begrenzt durch Korridor und Ladeleistung. Zeigt damit, wo der SOC-Deckel
  greift.
- Vergangene Stunden werden mit GEMESSENEN Werten aus der Historie
  gefuellt. Ohne das war das Diagramm bei einem Aufruf am Abend fast leer,
  weil die Projektion erst ab der aktuellen Stunde beginnt.

## [0.12.1] - 2026-08-15

### Fixed
- **"Lernfortschritt" zeigte einen irrefuehrenden Wert.** Gerechnet wurde
  `live_erfasste / alle Datensaetze` - bei frisch importierter Historie also
  2%, obwohl bereits alle 24 Stunden des Tages belegt waren. Der
  Fortschritt misst jetzt die Abdeckung des Lernzeitraums in Tagen.
- Die Kachel "Gelernte Stunden" zeigte die Anzahl live erfasster
  Datensaetze statt der abgedeckten Tagesstunden. Jetzt "Abgedeckte
  Stunden: X / 24", daneben getrennt die live erfassten.
- `get_statistics()` liefert zusaetzlich `hours_covered`, `days_covered`
  und `learning_days`.

### Changed
- `home_consumption_sensor` in config.yaml auf den neutralen Standard
  zurueckgesetzt. Die Datei enthaelt die Vorgaben fuer ALLE Nutzer und
  landet im oeffentlichen Repository - eigene Sensornamen gehoeren in die
  Add-on-Konfiguration von Home Assistant.

## [0.12.0] - 2026-08-15

### Added
- **Wirkungskontrolle** (`core/effectiveness.py`, `GET /api/effectiveness`,
  Karte im Dashboard): Wertet die SOC-Historie aus Home Assistant aus und
  beantwortet, ob die Strategie etwas gebracht hat.
  - Kennzahlen: Verweildauer ueber dem Korridor und ueber 95%, mittlerer
    Ladestand, Zeit unter der Untergrenze, geschaetzte Vollzyklen
  - Zeitanteile werden ueber die Dauer ZWISCHEN den Messpunkten gewichtet,
    nicht ueber deren Anzahl - HA schreibt nur bei Aenderung
  - Luecken ueber 3 Stunden werden ausgenommen, damit Ausfaelle die
    Anteile nicht verfaelschen
  - Vorher/Nachher-Vergleich anhand des vermerkten Scharfschaltzeitpunkts
  - Weist selbst darauf hin, wenn ein Zeitraum unter 7 Tagen liegt und das
    Ergebnis damit nicht belastbar ist
- `PVShapingPlanner.mark_live()`: vermerkt beim ersten echten Schreibvorgang
  den Zeitpunkt als Trennlinie der Auswertung.

### Fixed
- `timedelta` war in app.py nur lokal in einer Funktion importiert.

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
