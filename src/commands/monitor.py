from src.commands.auth import check_login

def add_monitor_subparsers(subparsers):
    """Fügt Monitoring-bezogene Befehle zum Parser hinzu."""
    ## Monitor-Befehl
    monitor_parser = subparsers.add_parser("monitor", help="Automatisch neue Beiträge überwachen und kommentieren")
    monitor_parser.add_argument("--interval", "-i", type=int, default=300, 
                               help="Zeitintervall zwischen den Prüfungen in Sekunden (Standard: 300)")
    monitor_parser.add_argument("--tab", "-t", default="alle", 
                               help="Tab, der überwacht werden soll: 'home' für Meine, 'alle' für Alle, oder ID eines Klassenraums")
    monitor_parser.add_argument("--comment", "-c", default="Interessanter Beitrag! Danke fürs Teilen.",
                               help="Kommentar-Text für neue Beiträge. {title}, {author} und {date} werden ersetzt.")
    monitor_parser.add_argument("--max-posts", "-m", type=int, default=20, 
                               help="Maximale Anzahl der zu prüfenden Beiträge pro Durchlauf (Standard: 20)")
    monitor_parser.add_argument("--max-runtime", "-r", type=int, 
                               help="Maximale Laufzeit in Sekunden, nicht angegeben für unbegrenzt")
    monitor_parser.set_defaults(func=cmd_monitor)
    
    ## Status-Befehl für bereits kommentierte Beiträge
    status_parser = subparsers.add_parser("monitor-status", help="Status der Überwachung und bereits kommentierte Beiträge anzeigen")
    status_parser.set_defaults(func=cmd_monitor_status)

def cmd_monitor(args, scraper):
    """Führt den Befehl zur automatischen Überwachung und Kommentierung aus."""
    check_login(scraper)
    
    print(f"Starte Überwachung im Tab '{args.tab}' mit Intervall von {args.interval} Sekunden...")
    print(f"Kommentar-Vorlage: '{args.comment}'")
    print("Drücke Strg+C, um die Überwachung zu beenden.")
    
    scraper.start_monitoring(
        interval=args.interval,
        tab=args.tab,
        comment_template=args.comment,
        max_posts=args.max_posts,
        max_runtime=args.max_runtime
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
