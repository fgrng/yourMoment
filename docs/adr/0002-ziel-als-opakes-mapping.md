# Ziel eines Monitoring Process als opakes Mapping

Ein Monitoring Process speichert sein Ziel als ein einziges String-Mapping (JSON), nicht in eigenen Spalten. Welche Schlüssel erlaubt sind, weiss nur der Adapter der Plattform: Er liefert eine statische Ziel-Beschreibung (Dimensionen mit Schlüssel, Label, Pflicht/optional), gegen die yourMoment beim Speichern ohne Netzwerk prüft, und über die Plattform-Verbindung die aktuellen Werte pro Dimension. Ob ein Wert auf der Plattform existiert, zeigt erst die Discovery. Die Datenbank kennt deshalb keine Constraints auf die Inhalte des Ziels.

So kann eine neue Plattform (WordPress) eigene Dimensionen mitbringen, ohne dass sich das Schema des Monitoring Process ändert. Der Suchbegriff bleibt ausserhalb des Ziels, weil yourMoment ihn selbst auf die Titel anwendet.

## Considered Options

- Getypte Spalten pro Plattform: DB-Constraints und einfache Abfragen, aber jede neue Plattform braucht eine Schema-Migration und das Model wächst mit jeder Plattform.
- Die myMoment-Spalten nur in Domänensprache umbenennen (#21): kleinster Eingriff, bindet den Monitoring Process aber dauerhaft an myMoment.
