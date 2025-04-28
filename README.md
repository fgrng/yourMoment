# myMoment Web Scraper

Dieses Tool ermöglicht die Interaktion mit der myMoment-Schreibplattform über die Kommandozeile. Es unterstützt das Anmelden, Auflisten von Beiträgen, Anzeigen einzelner Beiträge, Erstellen neuer Beiträge, Hinzufügen von Kommentaren und Vergeben von "Gefällt mir". Ein besonderes Feature ist die KI-gestützte automatische Kommentierung von Beiträgen.

## Installation

### Voraussetzungen

- Python 3.6 oder höher
- pip (Python-Paketmanager)

### Einrichtung

1. Klonen oder entpacken Sie das Projekt in ein Verzeichnis Ihrer Wahl.

2. Installieren Sie die benötigten Abhängigkeiten:

```bash
pip install requests beautifulsoup4 html-sanitizer
```

3. Um die KI-Funktionen zu nutzen (optional):

```bash
pip install mistralai
```

4. Machen Sie die Hauptdatei ausführbar (nur Linux/macOS):

```bash
chmod +x main.py
```

## Projektstruktur

```
mymoment-scraper/
├── main.py                # Hauptanwendung (Kommandozeilen-Interface)
├── src/
│   ├── __init__.py        # Paket-Initialisierungsdatei
│   ├── ai/                # KI-Module für automatische Kommentare
│   │   ├── __init__.py    # AI-Modul-Initialisierung
│   │   ├── base.py        # Basisklasse für Kommentierer
│   │   ├── mistral.py     # Mistral AI-Integration
│   │   └── template.py    # Vorlagenbasierte Kommentargenerierung
│   ├── commands/          # Kommandozeilenbefehle
│   │   ├── __init__.py    # Kommando-Modul-Initialisierung
│   │   ├── auth.py        # Authentifizierungsbefehle
│   │   ├── comments.py    # Kommentarbefehle
│   │   ├── monitor.py     # Überwachungsbefehle
│   │   └── posts.py       # Beitragsbefehle
│   ├── scraper/           # Web-Scraper-Funktionalität
│   │   ├── __init__.py    # Scraper-Modul-Initialisierung
│   │   ├── auth.py        # Authentifizierungslogik
│   │   ├── comments.py    # Kommentarverwaltung
│   │   ├── main.py        # Hauptscraper-Klasse
│   │   ├── monitor.py     # Überwachungsfunktionalität
│   │   └── posts.py       # Beitragsverwaltung
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

### Kommentare eines Beitrags anzeigen

```bash
python main.py comments BEITRAG_ID
```

Zeigt alle Kommentare eines bestimmten Beitrags an.

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

### Beitrag aktualisieren

```bash
python main.py update BEITRAG_ID --title "Neuer Titel" --content "Neuer Inhalt"
```

Nur die Parameter, die Sie angeben, werden aktualisiert. Die anderen bleiben unverändert.

### Beitrag veröffentlichen

```bash
python main.py publish BEITRAG_ID
```

Veröffentlicht einen Beitrag, der im Entwurfsmodus ist.

### Beitrag zurückziehen

```bash
python main.py draft BEITRAG_ID
```

Zieht einen veröffentlichten Beitrag zurück (als Entwurf markieren).

### Kommentar hinzufügen

```bash
python main.py comment BEITRAG_ID --text "Mein Kommentar zum Beitrag."
```

Optional können Sie einen Text im Beitrag hervorheben:

```bash
python main.py comment BEITRAG_ID --text "Mein Kommentar" --highlight "Dieser Teil des Textes"
```

### Kommentar bearbeiten

```bash
python main.py edit-comment KOMMENTAR_ID --text "Neuer Kommentartext"
```

Bearbeitet einen eigenen Kommentar. Die Kommentar-ID wird bei der Anzeige des Beitrags angezeigt, wenn es ein eigener Kommentar ist.

### "Gefällt mir" vergeben

```bash
python main.py like BEITRAG_ID
```

Fügt einem Beitrag ein "Gefällt mir" hinzu.

## KI-gestützte Kommentierung

Das Tool bietet KI-gestützte automatische Kommentargenerierung mit verschiedenen Optionen:

### KI-Kommentierer verwenden

Zur Einrichtung der MistralAI-Integration:

1. Besorgen Sie einen API-Schlüssel von MistralAI
2. Setzen Sie den API-Schlüssel als Umgebungsvariable:

```bash
export MISTRAL_API_KEY=Ihr_API_Schlüssel
```

Oder übergeben Sie ihn direkt beim Aufruf des Monitoring-Befehls.

### Beiträge überwachen und automatisch kommentieren

```bash
python main.py monitor
```

Diese Funktion prüft regelmäßig nach neuen Beiträgen und hinterlässt automatisch Kommentare. Standardmäßig wird alle 5 Minuten geprüft und ein allgemeiner Kommentar hinterlassen.

Optionen für erweiterte Kontrolle:

```bash
# Überwachung alle 10 Minuten
python main.py monitor --interval 600

# Bestimmten Tab überwachen
python main.py monitor --tab meine

# Personalisierter Kommentar mit Platzhaltern
python main.py monitor --comment "Ich finde deinen Beitrag '{title}' großartig, {author}!"

# Maximale Anzahl der zu prüfenden Beiträge pro Durchlauf
python main.py monitor --max-posts 50

# Automatisches Beenden nach 1 Stunde (3600 Sekunden)
python main.py monitor --max-runtime 3600

# Spezifischen KI-Kommentarstil verwenden (nur mit KI-Integration)
python main.py monitor --ai mistral --style questioning
```

Um den Status der Überwachung und bereits kommentierte Beiträge anzuzeigen:

```bash
python main.py monitor-status
```

Die Überwachung kann jederzeit mit der Tastenkombination `Strg+C` beendet werden.

### Verfügbare KI-Kommentarstile

Bei Verwendung der MistralAI-Integration stehen verschiedene Kommentarstile zur Auswahl:

- `motivation`: Ermutigt den Autor und gibt positives Feedback
- `questioning`: Stellt kritische Fragen zum Text, um den Autor zum Nachdenken anzuregen
- `arrangement_10`: Spezifischer Stil für das Schreibarrangement "Fiktionaler Dialog"

## Konfiguration

Die Anwendung erstellt automatisch eine Konfigurationsdatei unter `~/.mymoment_config.json`. Die Standard-URL ist `https://new.mymoment.ch`, kann aber bei Bedarf angepasst werden.

## Session-Management

Nach erfolgreicher Anmeldung mit der Option `--save` wird die Session lokal unter `~/.mymoment_session` gespeichert. Dies ermöglicht es, die Anwendung ohne erneutes Anmelden zu verwenden, solange die Session gültig ist.

## Beispiel-Workflow für eigene Beiträge

Ein typischer Workflow für eigene Beiträge könnte wie folgt aussehen:

1. Anmelden und Session speichern:
   ```bash
   python main.py login --save
   ```

2. Verfügbare Kategorien anzeigen:
   ```bash
   python main.py categories
   ```

3. Neuen Beitrag erstellen (standardmäßig als Entwurf):
   ```bash
   python main.py create --title "Mein erster Beitrag" --content "Hallo Welt!" --category 9
   ```

4. Beitrag bearbeiten:
   ```bash
   python main.py update 123 --content "Hallo Welt! Hier ist ein aktualisierter Inhalt."
   ```

5. Beitrag veröffentlichen:
   ```bash
   python main.py publish 123
   ```

6. Später den Beitrag wieder zurückziehen:
   ```bash
   python main.py draft 123
   ```

## Beispiel-Workflow für Interaktion mit anderen Beiträgen

Ein typischer Workflow für die Interaktion mit fremden Beiträgen:

1. Beiträge auflisten:
   ```bash
   python main.py list --tab alle
   ```

2. Einen bestimmten Beitrag anzeigen:
   ```bash
   python main.py show 90
   ```

3. Einen Kommentar hinterlassen:
   ```bash
   python main.py comment 90 --text "Das ist ein toller Beitrag!"
   ```

4. Einen Kommentar mit Texthervorhebung hinterlassen:
   ```bash
   python main.py comment 90 --text "Ist das richtig geschrieben?" --highlight "Gestern"
   ```

5. Dem Beitrag ein "Gefällt mir" geben:
   ```bash
   python main.py like 90
   ```

6. Später den eigenen Kommentar bearbeiten:
   ```bash
   python main.py edit-comment 186 --text "War das nicht heute? Ich bin mir nicht sicher."
   ```

## Beispiel für automatische KI-gestützte Interaktion

1. Anmelden und Session speichern:
   ```bash
   python main.py login --save
   ```

2. Monitoring mit MistralAI starten:
   ```bash
   python main.py monitor --interval 300 --tab alle --ai mistral --style motivation
   ```

3. In einem anderen Terminal den Status prüfen:
   ```bash
   python main.py monitor-status
   ```

## Hinweise

- Dieses Tool ist ein inoffizieller Client für die myMoment-Plattform.
- Da es auf Web-Scraping basiert, können Änderungen an der Website zu Funktionsstörungen führen.
- Die KI-Integration mit MistralAI erfordert einen gültigen API-Schlüssel und Internetverbindung.
- Verwenden Sie dieses Tool nur für legitime Zwecke und beachten Sie die Nutzungsbedingungen der myMoment-Plattform.

## Fehlerbehebung

Falls Probleme auftreten:

1. Stellen Sie sicher, dass Ihre Anmeldedaten korrekt sind.
2. Prüfen Sie Ihre Internetverbindung.
3. Für KI-Funktionen: Überprüfen Sie, ob der API-Schlüssel korrekt eingerichtet ist.
4. Bei anhaltenden Fehlern kann ein Update des Tools erforderlich sein, falls sich die Struktur der Website geändert hat.
