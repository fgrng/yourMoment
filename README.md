# myMoment Web Scraper

Dieses Tool ermöglicht die Interaktion mit der myMoment-Schreibplattform über die Kommandozeile. Es unterstützt das Anmelden, Auflisten von Beiträgen, Anzeigen einzelner Beiträge, Erstellen neuer Beiträge und Hinzufügen von Kommentaren.

## Installation

### Voraussetzungen

- Python 3.6 oder höher
- pip (Python-Paketmanager)

### Einrichtung

1. Klonen oder entpacken Sie das Projekt in ein Verzeichnis Ihrer Wahl.

2. Installieren Sie die benötigten Abhängigkeiten:

```bash
pip install requests beautifulsoup4
```

3. Machen Sie die Hauptdatei ausführbar (nur Linux/macOS):

```bash
chmod +x main.py
```

## Projektstruktur

```
mymoment-scraper/
├── main.py                # Hauptanwendung (Kommandozeilen-Interface)
├── src/
│   ├── __init__.py        # Paket-Initialisierungsdatei
│   ├── scraper.py         # Web-Scraper-Logik
│   └── config.py          # Konfigurationsmanagement
└── README.md              # Diese Datei
```

## Verwendung

### Anmelden

```bash
python main.py login
```

oder mit direkter Angabe des Benutzernamens:

```bash
python main.py login --username BENUTZERNAME
```

Beim Aufruf ohne Parameter werden Sie nach Benutzername und Passwort gefragt. Mit der Option `--save` wird die Session lokal gespeichert, um wiederholte Logins zu vermeiden.

### Beiträge auflisten

```bash
python main.py list
```

Standardmäßig werden die 10 neuesten Beiträge aus dem Tab "Meine" angezeigt. Weitere Optionen:

```bash
# 20 Beiträge anzeigen
python main.py list --count 20

# Beiträge aus anderen Tabs anzeigen
python main.py list --tab alle
python main.py list --tab 17  # 17 ist die ID des Klassenraums
```

### Einzelnen Beitrag anzeigen

```bash
python main.py show BEITRAG_ID
```

Ersetzt `BEITRAG_ID` durch die tatsächliche ID des Beitrags. Die IDs werden beim Auflisten der Beiträge angezeigt.

### Kategorien auflisten

```bash
python main.py categories
```

Zeigt alle verfügbaren Kategorien mit ihren IDs an.

### Neuen Beitrag erstellen

```bash
python main.py create --title "Mein Beitragstitel" --content "Hier ist der Inhalt des Beitrags."
```

Alternativ kann der Inhalt aus einer Datei geladen werden:

```bash
python main.py create --title "Mein Beitragstitel" --file inhalt.txt
```

Optional können Sie eine Kategorie angeben:

```bash
python main.py create --title "Mein Beitragstitel" --content "Inhalt" --category 9
```

### Kommentar hinzufügen

```bash
python main.py comment BEITRAG_ID --text "Mein Kommentar zum Beitrag."
```

Ersetzt `BEITRAG_ID` durch die tatsächliche ID des Beitrags.

## Konfiguration

Die Anwendung erstellt automatisch eine Konfigurationsdatei unter `~/.mymoment_config.json`. Die Standard-URL ist `https://new.mymoment.ch`, kann aber bei Bedarf angepasst werden.

## Session-Management

Nach erfolgreicher Anmeldung mit der Option `--save` wird die Session lokal unter `~/.mymoment_session` gespeichert. Dies ermöglicht es, die Anwendung ohne erneutes Anmelden zu verwenden, solange die Session gültig ist.

## Hinweise

- Dieses Tool ist ein inoffizieller Client für die myMoment-Plattform.
- Da es auf Web-Scraping basiert, können Änderungen an der Website zu Funktionsstörungen führen.
- Verwenden Sie dieses Tool nur für legitime Zwecke und beachten Sie die Nutzungsbedingungen der myMoment-Plattform.

## Fehlerbehebung

Falls Probleme auftreten:

1. Stellen Sie sicher, dass Ihre Anmeldedaten korrekt sind.
2. Prüfen Sie Ihre Internetverbindung.
3. Bei anhaltenden Fehlern kann ein Update des Tools erforderlich sein, falls sich die Struktur der Website geändert hat.
