# MAverage

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=RetGal_MAverage&metric=alert_status)](https://sonarcloud.io/dashboard?id=RetGal_MAverage)
![Python application](https://github.com/RetGal/MAverage/workflows/Python%20application/badge.svg)

## Voraussetzungen

*MAverage* setzt *Python* Version 3 oder grösser voraus.
Im Kern verwendet *MAverage* die [ccxt](https://github.com/ccxt/ccxt) Bibliothek. Diese gilt es mittels [pip](https://pypi.org/project/pip/) zu installieren:

`python -m pip install ccxt`

oder

`pip install -r requirements.txt`

Sollen die *MAverage* Instanzen via Watchdog überwacht und bei Bedarf nau gestartet werden, so wird zusätzlich noch [tmux](https://github.com/tmux/tmux/wiki) benötigt:

`apt install tmux`


## Inbetriebnahme
### Bot Instanzen
Vor dem Start ist die Konfigurationsdatei mit den gewünschten API Keys und Einstellungen zu ergänzen.

Bei der Initialisierung wird jeweils nach dem Namen der Konfigurationsdatei gefragt. Diesen ohne Endung (*.txt*) eingeben. 
Es können also mehrere config Dateien erstellt und immer dieselbe *maverage.py* Datei zum Start verwendet werden.

Alternativ kann die zu verwendete Konfigurationsdatei auch als Parameter übergeben werden:

`./maverage.py test1`

Mit Hilfe des Watchdog-Scrpits *[osiris](https://github.com/RetGal/osiris)* lässt sich eine beliebige Anzahl Botinstanzen überwachen.
Sollte eine Instanz nicht mehr laufen, wird sie automatisch neu gestartet. Daneben stellt der Watchdog auch sicher, dass stets genügend freier Speicher vorhanden ist.

Dazu sollte der Variable *workingDir* der absolute Pfad zum *maverage.py* Script angegeben werden.
Der *scriptName* sollte *maverage.py* lauten und der Wert von *exclude* sollte *mamaster* sein.
Voraussetzung ist, dass die *maverage.py* Instanzen innerhalb von *tmux* Sessions ausgeführt werden, welche gleich heissen wie die entsprechende Konfigurationsdatei:

Wenn also eine Konfigurationsdatei beispielsweise *test1.txt* heisst, dann sollte *maverage.py test1* innerhalb einer *tmux* Session namens *test1* laufen.

Damit *osiris.sh* die *MAverage*  Instanzen kontinuierlich überwachen kann, muss ein entsprechender *Cronjob* eingerichtet werden:

`*/5 *   *   *   *   /home/bot/movingaverage/osiris.sh`

Die beiden Dateien *maverage.py* und *osiris.sh* müssen vor dem ersten Start mittels `chmod +x` ausführbar gemacht werden.

### MAmaster

Um die konfigurierten Moving Average Werte berechnen zu können, benötigen die *MAverage* Instanzen aktuelle Kursdaten.
Diese holen sie sich aus der gemeinsamen *mamaster.db*. Diese wird durch *MAmaster* mit Werten befüllt, welche im 10 Minutenintervall abgefragt werden.

In der Konfigurationsdatei von *MAmaster* (*mamaster.txt*) muss dazu die abzufragende Börse eingetragen werden.
Anschliessend eine *MAmaster* Instanz innerhalb einer *tmux* Session starten:

`./mamaster.py`

Mit Hilfe des Watchdog-Scrpits *mamaster_osiris.sh* lässt sich die zentrale *MAmaster* Instanz überwachen.

Dazu sollte der Variable *workingDir* der absolute Pfad zum *mamaster.py* Script angegeben werden.

Damit *mamaster_osiris.sh* die *MAmaster*  Instanz kontinuierlich überwachen kann, muss ein entsprechender *Cronjob* eingerichtet werden:

`*/6 *   *   *   *   /home/bot/movingaverage/mamaster_osiris.sh`

Die beiden Dateien *mamaster.py* und *mamaster_osiris.sh* müssen vor dem ersten Start mittels `chmod +x` ausführbar gemacht werden.

## Unterbrechen

Wenn die *MAverage* Instanzen via *osiris* überwacht werden, steht man vor dem Problem, dass eine gestoppte Instanz nach spätestens 5 Minuten automatisch neu gestartet wird. Will man eine *MAverage* Instanz für längere Zeit unterbrechen, muss man vor oder nach dessen Terminierung die entsprechende *.pid* Datei umbenennen:

`mv test1.pid test1.did`

Dasselbe gilt für die *MAmaster* Instanz.

## Troubleshooting

Jede Instanz erstellt und schreibt in eine eigene Logdatei. Diese heisst so wie die entsprechende Konfigurationsdatei, beindet sich im `log` Verzeichnis endet aber auf *.log*:

`test1.log`

Fehlt diese Datei, dann konnte *maverage.py* nicht gestartet werden.
Die nächste Anlaufstelle wäre die entsprechende *tmux* Session:

`tmux a -t test1`

Sieht man da eine Fehlermeldung im Stil von:

`/usr/bin/python^M: bad interpreter`

Dann ist *maverage.py* wohl in einem Windows Editor bearbeitet, oder via einer populären MS Groupware versendet oder empfangen worden. Die folgenden Befehlsabfolge behebt das Problem:

`tr -d '\r' < maverage.py > MAverage && mv MAverage maverage.py && chmod +x maverage.py`
