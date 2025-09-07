from src.commands.auth import check_login

def add_monitor_subparsers(subparsers):
    """Fügt Monitoring-bezogene Befehle zum Parser hinzu."""
    ## Monitor-Befehl
    monitor_parser = subparsers.add_parser("monitor", help="Automatisch neue Beiträge überwachen und kommentieren")
    ## Basiskonfiguration für Monitoring
    monitor_parser.add_argument("--interval", "-i", type=int, default=300, 
                                help="Zeitintervall zwischen den Prüfungen in Sekunden (Standard: 300)")
    monitor_parser.add_argument("--tab", "-t", default="alle", 
                                help="Tab, der überwacht werden soll: 'home' für Meine, 'alle' für Alle, oder ID eines Klassenraums")
    monitor_parser.add_argument("--category", "-c", type=int, default=0, 
                                help="ID der Beitragskategorie: 9 für 'Informieren', 10 für 'Schreibaufgabe Fiktionaler Dialog', etc.")
    monitor_parser.add_argument("--hidden", action="store_true", 
                                help="Kommentare versteckt hinterlassen (nur für Lehrpersonen sichtbar)")
    monitor_parser.add_argument("--dry-run", action="store_true",
                                help="Generiert Kommentare, postet sie aber nicht")
    monitor_parser.add_argument("--max-posts", "-m", type=int, default=20, 
                                help="Maximale Anzahl der zu prüfenden Beiträge pro Durchlauf (Standard: 20)")
    monitor_parser.add_argument("--max-runtime", "-r", type=int, 
                                help="Maximale Laufzeit in Sekunden, nicht angegeben für unbegrenzt")
    
    ## Templates für Kommentare
    monitor_parser.add_argument("--comment", "-C", default="Interessanter Beitrag! Danke fürs Teilen.",
                                help="Kommentar-Text für neue Beiträge. {title}, {author} und {date} werden ersetzt.")
    monitor_parser.add_argument("--commenter", choices=["template", "mistral"], 
                                default="template", help="Auswahl des Kommentierers.")
    monitor_parser.add_argument("--style", "-s", choices=["motivation", "questioning", "arrangement_10"], 
                                default="motivation", help="Stil der KI-Kommentare (Standard: motivation)")
    monitor_parser.add_argument("--mistral-model", default="mistral-small-latest",
                                help="Zu verwendendes Mistral-Modell (Standard: mistral-small-latest)")
    monitor_parser.add_argument("--api-key", help="Mistral API-Schlüssel (alternativ: MISTRAL_API_KEY Umgebungsvariable)")

    # monitor_parser.add_argument("--highlight", action="store_true",
    #                         help="Zufällige Textstellen hervorheben und kommentieren")

    monitor_parser.set_defaults(func=cmd_monitor)
    
    ## Status-Befehl für bereits kommentierte Beiträge
    status_parser = subparsers.add_parser("monitor-status", help="Status der Überwachung und bereits kommentierte Beiträge anzeigen")
    status_parser.set_defaults(func=cmd_monitor_status)

def cmd_monitor(args, scraper):
    """Führt den Befehl zur automatischen Überwachung und Kommentierung aus."""
    check_login(scraper)
    
    print(f"Starte Überwachung im Tab '{args.tab}' mit Intervall von {args.interval} Sekunden...")
    print(f"Kommentar-Vorlage: '{args.comment}'")
    if args.hidden:
        print("Kommentare werden versteckt erstellt.")
    if args.dry_run:
        print("Kommentare werden nur lokal erstellt und nicht abgeschickt (dry-run).")
    print("Drücke Strg+C, um die Überwachung zu beenden.")


    ## Kommentierer wählen
    commenter = None
    ## LLM Funktionen
    if args.commenter == "mistral":
        try:
            from src.ai import MistralAICommenter
            commenter = MistralAICommenter(
                api_key=args.api_key, 
                model=args.mistral_model,
                style=args.style,
                hidden=args.hidden
            )
            print(f"KI-Kommentare sind aktiviert. Verwende Modell: {args.mistral_model}. Stil: {args.style}.")
        except ImportError:
            print("Fehler: Das mistralai-Paket ist nicht installiert.")
            print("Bitte installieren Sie es mit: pip install mistralai")
            return
        except ValueError as e:
            print(f"Fehler bei der Initialisierung von Mistral AI: {e}")
            print("Bitte setzen Sie die MISTRAL_API_KEY Umgebungsvariable oder übergeben Sie --api-key")
            return

    if args.commenter == "template":
        try:
            from src.ai import TemplateCommenter
            commenter = TemplateCommenter()
            print("Template-Kommentierer initialisiert")
        except ImportError as e:
            print(f"Fehler beim Laden des Template-Kommentierers: {e}")
            return

    # if args.highlight:
    #     print("Textstellen werden hervorgehoben und kommentiert")

    scraper.start_monitoring(
        interval=args.interval,
        tab=args.tab,
        category=args.category,
        commenter=commenter,
        max_posts=args.max_posts,
        max_runtime=args.max_runtime,
        dry_run=args.dry_run,
        hidden=args.hidden
    )

def cmd_monitor_status(args, scraper):
    """Zeigt den Status der Überwachung und bereits kommentierte Beiträge an."""
    check_login(scraper)
    
    ## Monitor-Instanz abrufen
    monitor = scraper.get_monitor()
    
    ## Kommentierte Beiträge laden
    commented_posts = monitor.load_commented_posts()
    
    print("\nStatus der Beitrags-Überwachung:")
    print("-" * 80)
    
    ## Letzten Check anzeigen
    last_check = commented_posts.get("last_check", "Noch keine Überwachung durchgeführt")
    print(f"Letzter Check: {last_check}")
    
    ## Anzahl der kommentierten Beiträge
    num_commented = len(commented_posts.get("posts", {}))
    print(f"Bereits kommentierte Beiträge: {num_commented}")
    
    ## Aktive Überwachung
    if monitor.running:
        print("Status: Aktiv")
    else:
        print("Status: Inaktiv")
    
    ## Details zu kommentierten Beiträgen
    if num_commented > 0:
        print("\nKommentierte Beiträge:")
        print("-" * 80)
        
        for post_id, details in commented_posts.get("posts", {}).items():
            commented_at = details.get("commented_at", "Unbekannt")
            comment_text = details.get("comment_text", "Unbekannt")
            
            print(f"Beitrag-ID: {post_id}")
            print(f"Kommentiert am: {commented_at}")
            print(f"Kommentar: {comment_text}")
            print("-" * 80)
