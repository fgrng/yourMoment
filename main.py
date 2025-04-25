import argparse
import sys
import os
from src.scraper import WebScraper
from src.config import load_config, save_config

def main():
    parser = argparse.ArgumentParser(description="Kommandozeilen-Client für myMoment Schreibplattform")
    subparsers = parser.add_subparsers(dest="command", help="Befehle")
    
    ## Login-Befehl
    login_parser = subparsers.add_parser("login", help="Bei der Plattform anmelden")
    login_parser.add_argument("--username", "-u", help="Benutzername")
    login_parser.add_argument("--password", "-p", help="Passwort")
    login_parser.add_argument("--save", action="store_true", help="Anmeldedaten speichern")
    
    ## Posts auflisten
    list_parser = subparsers.add_parser("list", help="Alle Beiträge auflisten")
    list_parser.add_argument("--count", "-c", type=int, default=10, help="Anzahl der anzuzeigenden Beiträge")
    list_parser.add_argument("--tab", "-t", default="home", help="Tab, der angezeigt werden soll: 'home' für Meine, 'alle' für Alle, oder ID eines Klassenraums")
    
    ## Einzelnen Post anzeigen
    show_parser = subparsers.add_parser("show", help="Einzelnen Beitrag anzeigen")
    show_parser.add_argument("post_id", help="ID des Beitrags")
    
    ## Kommentare eines Beitrags anzeigen
    comments_parser = subparsers.add_parser("comments", help="Kommentare eines Beitrags anzeigen")
    comments_parser.add_argument("post_id", help="ID des Beitrags")
    
    ## Neuen Post erstellen
    create_parser = subparsers.add_parser("create", help="Neuen Beitrag erstellen")
    create_parser.add_argument("--title", "-t", required=True, help="Titel des Beitrags")
    create_parser.add_argument("--content", "-c", help="Inhalt des Beitrags")
    create_parser.add_argument("--file", "-f", help="Datei mit Inhalt des Beitrags")
    create_parser.add_argument("--category", "-g", help="Kategorie-ID des Beitrags")
    
    ## Beitrag aktualisieren
    update_parser = subparsers.add_parser("update", help="Beitrag aktualisieren")
    update_parser.add_argument("post_id", help="ID des Beitrags")
    update_parser.add_argument("--title", "-t", help="Neuer Titel des Beitrags")
    update_parser.add_argument("--content", "-c", help="Neuer Inhalt des Beitrags")
    update_parser.add_argument("--file", "-f", help="Datei mit neuem Inhalt des Beitrags")
    update_parser.add_argument("--category", "-g", help="Neue Kategorie-ID des Beitrags")
    update_parser.add_argument("--status", "-s", help="Neuer Status des Beitrags (10=Entwurf, 20=Publiziert)")
    
    ## Beitrag veröffentlichen
    publish_parser = subparsers.add_parser("publish", help="Beitrag veröffentlichen")
    publish_parser.add_argument("post_id", help="ID des Beitrags")
    
    ## Beitrag zurückziehen
    draft_parser = subparsers.add_parser("draft", help="Beitrag zurückziehen")
    draft_parser.add_argument("post_id", help="ID des Beitrags")
    
    ## Kommentar hinzufügen
    comment_parser = subparsers.add_parser("comment", help="Kommentar zu einem Beitrag hinzufügen")
    comment_parser.add_argument("post_id", help="ID des Beitrags")
    comment_parser.add_argument("--text", "-t", required=True, help="Text des Kommentars")
    comment_parser.add_argument("--highlight", "-H", help="Hervorgehobener Text im Beitrag")
    
    ## Kommentar bearbeiten
    edit_comment_parser = subparsers.add_parser("edit-comment", help="Eigenen Kommentar bearbeiten")
    edit_comment_parser.add_argument("comment_id", help="ID des Kommentars")
    edit_comment_parser.add_argument("--text", "-t", required=True, help="Neuer Text des Kommentars")
    
    ## Kategorien auflisten
    categories_parser = subparsers.add_parser("categories", help="Verfügbare Kategorien auflisten")
    
    ## Like-Befehl
    like_parser = subparsers.add_parser("like", help="Einem Beitrag einen 'Gefällt mir' hinzufügen")
    like_parser.add_argument("post_id", help="ID des Beitrags")
    
    args = parser.parse_args()
    
    ## Konfiguration laden
    config = load_config()
    
    ## WebScraper-Instanz erstellen
    scraper = WebScraper(config.get("base_url", "https://new.mymoment.ch"))
    
    ## Befehl ausführen
    if args.command == "login":
        username = args.username or input("Benutzername: ")
        password = args.password or input("Passwort: ")
        print(f"Versuche Login als {username}...")
        success = scraper.login(username, password)
        if success:
            print("Login erfolgreich!")
            if args.save:
                ## Speichern der Session
                scraper.save_session()
        else:
            print("Login fehlgeschlagen!")
            sys.exit(1)
            
    elif args.command == "list":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        
        print(f"Lade Beiträge aus Tab '{args.tab}'...")
        posts = scraper.get_posts(args.count, args.tab)
        
        if posts:
            print(f"\nGefundene Beiträge ({len(posts)}):")
            print("-" * 80)
            for post in posts:
                print(f"ID: {post['id']} | Status: {post['status']}")
                print(f"Titel: {post['title']}")
                print(f"Autor: {post['author']} | Datum: {post['date']}")
                print(f"Sichtbar für: {post['visibility']}")
                print(f"URL: {post['url']}")
                print("-" * 80)
        else:
            print("Keine Beiträge gefunden.")
            
    elif args.command == "show":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        
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
            
            ## Kommentare anzeigen, falls vorhanden
            if post.get('comments'):
                print(f"\nKOMMENTARE ({len(post['comments'])}):")
                for comment in post['comments']:
                    print(f"- {comment['author']} ({comment['date']})")
                    if comment.get('highlight'):
                        print(f"  Hervorgehobener Text: \"{comment['highlight']}\"")
                    print(f"  {comment['text']}")
                    if comment.get('can_edit'):
                        print(f"  [Kommentar-ID: {comment['id']} - kann bearbeitet werden]")
                    print()
            elif is_edit_mode:
                print("\nHinweis: Beitrag im Bearbeitungsmodus.")
                
        else:
            print(f"Beitrag mit ID {args.post_id} nicht gefunden.")
    
    elif args.command == "comments":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        
        print(f"Lade Kommentare für Beitrag mit ID {args.post_id}...")
        comments = scraper.get_comments(args.post_id)
        
        if comments:
            print(f"\nGefundene Kommentare ({len(comments)}):")
            print("-" * 80)
            for comment in comments:
                print(f"Autor: {comment['author']} | Datum: {comment['date']}")
                if comment.get('highlight'):
                    print(f"Hervorgehobener Text: \"{comment['highlight']}\"")
                print(f"Text: {comment['text']}")
                if comment.get('can_edit'):
                    print(f"[Kommentar-ID: {comment['id']} - kann bearbeitet werden]")
                print("-" * 80)
        else:
            print("Keine Kommentare gefunden.")
            
    elif args.command == "create":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        
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
    
    elif args.command == "update":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        
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
    
    elif args.command == "publish":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        
        print(f"Veröffentliche Beitrag mit ID {args.post_id}...")
        success = scraper.publish_post(args.post_id)
        
        if success:
            print("Beitrag erfolgreich veröffentlicht!")
        else:
            print("Fehler beim Veröffentlichen des Beitrags.")
    
    elif args.command == "draft":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        
        print(f"Ziehe Beitrag mit ID {args.post_id} zurück...")
        success = scraper.draft_post(args.post_id)
        
        if success:
            print("Beitrag erfolgreich zurückgezogen!")
        else:
            print("Fehler beim Zurückziehen des Beitrags.")
            
    elif args.command == "comment":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        
        print(f"Füge Kommentar zu Beitrag {args.post_id} hinzu...")
        success = scraper.add_comment(args.post_id, args.text, args.highlight)
        
        if success:
            print("Kommentar erfolgreich hinzugefügt!")
        else:
            print("Fehler beim Hinzufügen des Kommentars.")
    
    elif args.command == "edit-comment":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        
        print(f"Bearbeite Kommentar mit ID {args.comment_id}...")
        success = scraper.edit_comment(args.comment_id, args.text)
        
        if success:
            print("Kommentar erfolgreich bearbeitet!")
        else:
            print("Fehler beim Bearbeiten des Kommentars.")
            
    elif args.command == "categories":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        
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
    
    elif args.command == "like":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        
        print(f"Füge 'Gefällt mir' zu Beitrag {args.post_id} hinzu...")
        success = scraper.like_post(args.post_id)
        
        if success:
            print("'Gefällt mir' erfolgreich hinzugefügt!")
        else:
            print("Fehler beim Hinzufügen von 'Gefällt mir'.")
            
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
