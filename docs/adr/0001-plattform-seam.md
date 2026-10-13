# Plattformen nur über ein Plattform-Interface, gewählt pro Plattform-Account

yourMoment soll auf myMoment und auf WordPress handeln können. Wir sprechen jede Plattform deshalb nur über ein gemeinsames Plattform-Interface an: Verbindung pro Plattform-Account, Artikel auflisten, Artikel lesen, Kommentar posten, Artikel von Schüler:innen auflisten. Hinter dem Interface sitzt pro Plattform ein Adapter. Die Plattform wird pro Plattform-Account gewählt, nicht global, damit beide Plattformen parallel betrieben werden können. Login, Sitzung und Cookie-Persistenz sind Implementierungsdetails des Adapters und nicht Teil des Interfaces.

WordPress wird über die REST API mit Application Passwords angebunden, nicht wie myMoment per HTML-Scraping. Die REST API liefert getypte Antworten, echte Kommentar-IDs und Revisionen und braucht keine Cookie-Session. Die Instanz muss dafür REST API und Application Passwords zulassen.

## Considered Options

- Plattform global per Setting wählen: einfacher, verbaut aber den Parallelbetrieb.
- WordPress scrapen oder XML-RPC nutzen: abgelehnt, weil beides fragil ist und keine stabile Identität für Kommentare liefert.
