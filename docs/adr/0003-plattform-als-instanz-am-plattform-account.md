# Plattform als Instanz, identifiziert über Typ und Base-URL am Plattform-Account

Eine Plattform ist eine konkrete Instanz, etwa myMoment oder eine bestimmte WordPress-Instanz. Identifiziert wird sie über das Paar aus Plattform-Typ und normalisierter Base-URL, das jeder Plattform-Account trägt (`platform`, `base_url`). Eine eigene Tabelle für Plattformen gibt es nicht. Beide Angaben sind nach dem Anlegen eines Accounts fest. Ein Monitoring Process leitet seine Plattform aus seinen Accounts ab: Alle Accounts müssen zur selben Plattform gehören, und ein Wechsel auf eine andere Plattform wird abgelehnt. Weil sich nichts davon ändern kann, kann die Ableitung nicht auseinanderlaufen, und bestehende AI Comments, Tracked Students und Article Versions behalten ihre Plattform.

## Considered Options

- Eigene Tabelle `platforms`, auf die Accounts verweisen: Eindeutigkeit und Plattform eines Prozesses wären per Fremdschlüssel ausdrückbar. Dafür wäre die Plattform eine weitere Entität, die angelegt und verwaltet werden muss, obwohl jeder User sie ohnehin über seine Accounts angibt.
- Plattform als eigenes Feld am Monitoring Process: Das ist eine Kopie, die neben den Accounts auseinanderlaufen kann.
- Plattformwechsel eines Prozesses erlauben: Dann wäre offen, was mit seinen bestehenden AI Comments und seinem Ziel geschieht. Stattdessen wird ein neuer Prozess angelegt.
