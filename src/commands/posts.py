import sys
from src.commands.auth import check_login

def add_post_subparsers(subparsers):
    """Fügt Post-bezogene Befehle zum Parser hinzu."""
    ## Posts auflisten
    list_parser = subparsers.add_parser("list", help="Alle Beiträge auflisten")
    list_parser.add_argument("--count", "-c", type=int, default=10, help="Anzahl der anzuzeigenden Beiträge")
    list_parser.add_argument("--tab", "-t", default="home", help="Tab, der angezeigt werden soll: 'home' für Meine, 'alle' für Alle, oder ID eines Klassenraums")
    list_parser.set_defaults(func=cmd_list_posts)
    
    ## Einzelnen Post anzeigen
    show_parser = subparsers.add_parser("show", help="Einzelnen Beitrag anzeigen")
    show_parser.add_argument("post_id", help="ID des Beitrags")
    show_parser.set_defaults(func=cmd_show_post)
    
    ## Neuen Post erstellen
    create_parser = subparsers.add_parser("create", help="Neuen Beitrag erstellen")
    create_parser.add_argument("--title", "-t", required=True, help="Titel des Beitrags")
    create_parser.add_argument("--content", "-c", help="Inhalt des Beitrags")
    create_parser.add_argument("--file", "-f", help="Datei mit Inhalt des Beitrags")
    create_parser.add_argument("--category", "-g", help="Kategorie-ID des Beitrags")
    create_parser.set_defaults(func=cmd_create_post)
    
    ## Beitrag aktualisieren
    update_parser = subparsers.add_parser("update", help="Beitrag aktualisieren")
    update_parser.add_argument("post_id", help="ID des Beitrags")
    update_parser.add_argument("--title", "-t", help="Neuer Titel des Beitrags")
    update_parser.add_argument("--content", "-c", help="Neuer Inhalt des Beitrags")
    update_parser.add_argument("--file", "-f", help="Datei mit neuem Inhalt des Beitrags")
    update_parser.add_argument("--category", "-g", help="Neue Kategorie-ID des Beitrags")
    update_parser.add_argument("--status", "-s", help="Neuer Status des Beitrags (10=Entwurf, 20=Publiziert)")
    update_parser.set_defaults(func=cmd_update_post)
    
    ## Beitrag veröffentlichen
    publish_parser = subparsers.add_parser("publish", help="Beitrag veröffentlichen")
    publish_parser.add_argument("post_id", help="ID des Beitrags")
    publish_parser.set_defaults(func=cmd_publish_post)
    
    ## Beitrag zurückziehen
    draft_parser = subparsers.add_parser("draft", help="Beitrag zurückziehen")
    draft_parser.add_argument("post_id", help="ID des Beitrags")
    draft_parser.set_defaults(func=cmd_draft_post)
    
    ## Like-Befehl
    like_parser = subparsers.add_parser("like", help="Einem Beitrag einen 'Gefällt mir' hinzufügen")
    like_parser.add_argument("post_id", help="ID des Beitrags")
    like_parser.set_defaults(func=cmd_like_post)
    
    ## Kategorien auflisten
    categories_parser = subparsers.add_parser("categories", help="Verfügbare Kategorien auflisten")
    categories_parser.set_defaults(func=cmd_list_categories)

def cmd_list_posts(args, scraper):
    """Führt den Befehl zum Auflisten von Beiträgen aus."""
    check_login(scraper)
    
    print(f"Lade Beiträge aus Tab '{args.tab}'...")
    posts = scraper.get_posts(args.count, args.tab)
    
    if posts:
        print(f"\nGefundene Beiträge ({len(posts)}):")
        print("-" * 80)
        for post in posts:
            print(f"ID: {post['id']} | Status: {post['status']}")
            print(f"Titel: {post['title']}")
            print(f"Category: {post['category_id']}")
            print(f"Autor: {post['author']} | Datum: {post['date']}")
            print(f"Sichtbar für: {post['visibility']}")
            print(f"URL: {post['url']}")
            print("-" * 80)
    else:
        print("Keine Beiträge gefunden.")

def cmd_show_post(args, scraper):
    """Führt den Befehl zum Anzeigen eines einzelnen Beitrags aus."""
    check_login(scraper)
    
    print(f"Lade Beitrag mit ID {args.post_id}...")
    post = scraper.get_post(args.post_id)
    
    if post:
        is_edit_mode = post.get('is_edit_mode', False)
        is_own_post = post.get('is_own_post', False)
        
        print("\n" + "=" * 80)
        print(f"Titel: {post['title']}")
        print(f"Autor: {post['author']}")
        print(f"Datum: {post['date']}")
        print(f"Status: {post.get('status', 'Unbekannt')}")
        
        if is_own_post:
            print("Dies ist dein eigener Beitrag.")
        
        ## Statistiken anzeigen, falls vorhanden
        if post.get('stats'):
            stats_str = " | ".join([f"{k}: {v}" for k, v in post['stats'].items()])
            print(f"Statistik: {stats_str}")
            
        print("=" * 80)
        
        print("\nINHALT:")
        print(post['content'])
        print("-" * 80)

        print("\nINHALT (HTML):")
        print(post['full_html'])
        print("-" * 80)
        
        ## Kommentare anzeigen, falls vorhanden
        if post.get('comments'):
            print(f"\nKOMMENTARE ({len(post['comments'])}):")
            for comment in post['comments']:
                print(f"- {comment['author']} ({comment['date']})")
                if comment.get('highlight'):
                    print(f"  Hervorgehobener Text: \"{comment['highlight']}\"")
                print(f"  INHALT:")
                print(f"  {comment['text']}")
                print(f"  INHALT (HTML):")
                print(f"  {comment['full_html']}")
                if comment.get('can_edit'):
                    print(f"  [Kommentar-ID: {comment['id']} - kann bearbeitet werden]")
                print()
        elif is_edit_mode:
            print("\nHinweis: Beitrag im Bearbeitungsmodus.")
            
    else:
        print(f"Beitrag mit ID {args.post_id} nicht gefunden.")

def cmd_create_post(args, scraper):
    """Führt den Befehl zum Erstellen eines neuen Beitrags aus."""
    check_login(scraper)
    
    content = args.content
    if args.file:
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"Fehler beim Lesen der Datei: {e}")
            sys.exit(1)
    
    if not content:
        print("Bitte geben Sie den Inhalt des Beitrags ein (beenden mit Strg+D):")
        content = sys.stdin.read()
    
    print(f"Erstelle neuen Beitrag '{args.title}'...")
    success, post_id = scraper.create_post(args.title, content, args.category)
    
    if success:
        print(f"Beitrag erfolgreich erstellt! ID: {post_id}")
        print(f"URL: {scraper.base_url}/article/{post_id}/")
    else:
        print("Fehler beim Erstellen des Beitrags.")

def cmd_update_post(args, scraper):
    """Führt den Befehl zum Aktualisieren eines Beitrags aus."""
    check_login(scraper)
    
    content = args.content
    if args.file:
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"Fehler beim Lesen der Datei: {e}")
            sys.exit(1)
    
    print(f"Aktualisiere Beitrag mit ID {args.post_id}...")
    success = scraper.update_post(
        args.post_id, 
        title=args.title, 
        content=content,
        category_id=args.category,
        status_id=args.status
    )
    
    if success:
        print("Beitrag erfolgreich aktualisiert!")
    else:
        print("Fehler beim Aktualisieren des Beitrags.")

def cmd_publish_post(args, scraper):
    """Führt den Befehl zum Veröffentlichen eines Beitrags aus."""
    check_login(scraper)
    
    print(f"Veröffentliche Beitrag mit ID {args.post_id}...")
    success = scraper.publish_post(args.post_id)
    
    if success:
        print("Beitrag erfolgreich veröffentlicht!")
    else:
        print("Fehler beim Veröffentlichen des Beitrags.")

def cmd_draft_post(args, scraper):
    """Führt den Befehl zum Zurückziehen eines Beitrags aus."""
    check_login(scraper)
    
    print(f"Ziehe Beitrag mit ID {args.post_id} zurück...")
    success = scraper.draft_post(args.post_id)
    
    if success:
        print("Beitrag erfolgreich zurückgezogen!")
    else:
        print("Fehler beim Zurückziehen des Beitrags.")

def cmd_like_post(args, scraper):
    """Führt den Befehl zum Hinzufügen eines 'Gefällt mir' aus."""
    check_login(scraper)
    
    print(f"Füge 'Gefällt mir' zu Beitrag {args.post_id} hinzu...")
    success = scraper.like_post(args.post_id)
    
    if success:
        print("'Gefällt mir' erfolgreich hinzugefügt!")
    else:
        print("Fehler beim Hinzufügen von 'Gefällt mir'.")

def cmd_list_categories(args, scraper):
    """Führt den Befehl zum Auflisten der Kategorien aus."""
    check_login(scraper)
    
    print("Lade verfügbare Kategorien...")
    categories = scraper.get_categories()
    
    if categories:
        print("\nVerfügbare Kategorien:")
        print("-" * 50)
        for category in categories:
            print(f"ID: {category['id']} | Name: {category['name']}")
        print("-" * 50)
        print("Tipp: Verwenden Sie die Kategorie-ID mit dem 'create' Befehl (--category)")
    else:
        print("Keine Kategorien gefunden.")
