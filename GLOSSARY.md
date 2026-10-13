# yourMoment

yourMoment beobachtet im Auftrag von Lehrpersonen und Forschenden Schüler:innen-Texte auf einer externen Schreibplattform, erzeugt dazu LLM-generierte Kommentare, veröffentlicht sie dort und archiviert die Texte. yourMoment ist ein eigenständiges System *neben* der Plattform und kontrolliert sie nicht.

## Language

### Plattformen und Akteure

**Plattform**:
Die externe Schreibplattform, auf der Students Texte verfassen und kommentiert werden: myMoment oder eine WordPress-Instanz.
_Avoid_: Scraper, Site, Blog (für die Plattform als Ganzes)

**myMoment**:
Die bestehende Schreibplattform, auf der Primarschüler:innen Texte verfassen, veröffentlichen und einander kommentieren; die erste und bisher einzige angebundene Plattform.

**User**:
Ein registrierter yourMoment-Nutzer (Lehrperson oder Forschende:r), der Monitoring Processes, Plattform-Accounts, Prompt Templates und LLM-Konfigurationen besitzt. Alle Daten sind pro User isoliert.
_Avoid_: Account (allein), Nutzer

**Student**:
Ein:e Schüler:in *auf einer Plattform*, deren Texte beobachtet oder gesichert werden. Ein Student hat kein yourMoment-Konto.
_Avoid_: Schüler-User, Studierende:r

**Plattform-Account**:
Ein hinterlegtes, verschlüsseltes Zugangskonto eines Users zu genau einer Plattform. Ein User kann mehrere besitzen; ein Plattform-Account ist entweder ein normaler Account (fürs Kommentieren) oder ein **Admin-Account**.
_Avoid_: MyMoment Login, Login, Credentials (nur für das verschlüsselte Feld)

**Admin-Account**:
Ein Plattform-Account mit erweiterten Rechten, der die Texte aller Students einsehen darf. Admin-Accounts werden *ausschliesslich* fürs Student Backup verwendet und kommentieren **nie** in Monitoring Processes.
_Avoid_: Admin Login

**MyMoment Session**:
Eine ablaufende Anmeldesitzung bei myMoment für genau einen Plattform-Account; andere Plattformen kennen keine Sitzung. Nicht zu verwechseln mit der **User Session**, der Anmeldung eines Users in der yourMoment-Web-App.

### Artikel

**Artikel-Referenz**:
Die Identität eines Artikels auf seiner Plattform: die von der Plattform vergebene ID und seine absolute URL.
_Avoid_: mymoment_article_id, Artikel-ID (allein)

**Category**:
Die kommunikative Funktion eines myMoment-Texts (z. B. Anleiten, Berichten, Unterhalten).
_Avoid_: Rubrik, Genre

**Arrangement**:
Die Zuordnung eines myMoment-Texts zu einer konkreten Schreibaufgabe (z. B. „Fiktionaler Dialog zwischen zwei Gegenständen“).
_Avoid_: Task, Aufgabe

**Classroom**:
Die Zuordnung eines myMoment-Texts zu einer Klasse oder Gruppe, die die Sichtbarkeit bei der Veröffentlichung regelt.
_Avoid_: Tab, Klasse

### Monitoring und Kommentierung

**Monitoring Process**:
Ein vom User konfigurierter, zeitlich begrenzter Hintergrundprozess, der Artikel auf einer Plattform nach festgelegten Kriterien entdeckt und für sie AI Comments erzeugt und optional veröffentlicht. Er nutzt Plattform-Accounts genau einer Plattform und hat einen Status (created, running, stopped, completed, failed).
_Avoid_: Job, Task

**Ziel**:
Das, was ein Monitoring Process auf seiner Plattform beobachtet. Welche Dimensionen ein Ziel hat, bestimmt die Plattform; bei myMoment sind es Category, Arrangement und Classroom (Classroom ist Pflicht). Der Suchbegriff gehört nicht zum Ziel, sondern ist ein plattformunabhängiger Titelfilter des Monitoring Process.
_Avoid_: Filter, Tab, target_filters

**Generate-Only**:
Ein Modus eines Monitoring Process, in dem AI Comments nur erzeugt, aber nicht veröffentlicht werden. Solche Kommentare können später manuell veröffentlicht werden.

**Pipeline**:
Der idempotente Ablauf, den jeder entdeckte Artikel innerhalb eines Monitoring Process durchläuft: **discovered** → **prepared** → **generated** → **posting** → **posted**. Die beiden letzten Stufen entfallen im Generate-Only-Modus; Fehlerzustand ist **failed**.

**AI Comment**:
Der zentrale Datensatz einer einzelnen Kommentier-Aktion. Er bündelt den Article Snapshot, den generierten Kommentartext samt Modell- und Provider-Angaben und die Verknüpfung zu Plattform-Account, Monitoring Process und Prompt Template.
_Avoid_: Comment (allein; immer AI Comment, um ihn von Kommentaren Dritter zu unterscheiden)

**Article Snapshot**:
Die im AI Comment eingefrorene Kopie eines Artikels (Titel, Autor:in, Text, Roh-HTML) zum Bearbeitungszeitpunkt; dient als revisionssicherer Audit-Trail.

**AI Disclosure Prefix**:
Der verpflichtende deutschsprachige Hinweis, der jedem veröffentlichten AI Comment vorangestellt wird und die KI-Herkunft offenlegt. Er zählt nicht zur konfigurierten Kommentarlänge.

### Prompts und LLM

**Prompt Template**:
Eine wiederverwendbare Vorlage zur Erzeugung von AI Comments aus System-Prompt und User-Prompt mit Platzhaltern. Entweder **System-Template** (mitgeliefert, für alle Users) oder **User-Template** (einem User gehörend).
_Avoid_: Prompt (allein)

**Prompt Weight**:
Das Gewicht, mit dem ein Prompt Template in einem Monitoring Process bei der zufälligen Auswahl berücksichtigt wird; ein Prozess kann mehrere Templates gewichtet mischen.

**LLM Provider Configuration**:
Die Konfiguration eines LLM-Anbieters durch einen User (Anbieter, Modell, Parameter) inklusive verschlüsseltem API-Key.
_Avoid_: Provider (allein), API-Config

### Student Backup

**Student Backup**:
Das von der Kommentierung getrennte Feature, das die Texte der Tracked Students periodisch sichert und versioniert. Es nutzt ausschliesslich Admin-Accounts.

**Tracked Student**:
Ein für das Student Backup ausgewählter Student, identifiziert über seine ID auf der Plattform und einem Admin-Account zugeordnet. Ein User kann denselben Student nur einmal verfolgen.

**Article Version**:
Ein fortlaufend nummerierter Stand eines Artikels eines Tracked Student; ein inhaltlich unveränderter Artikel erzeugt keine neue Version. Unabhängig vom Article Snapshot der Pipeline.
