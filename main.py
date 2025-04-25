import argparse
import sys
from src.scraper import WebScraper
from src.config import load_config

def main():
    parser = argparse.ArgumentParser(description="Kommandozeilen-Client für Schreibplattform")
    subparsers = parser.add_subparsers(dest="command", help="Befehle")
    
    ## Login-Befehl
    login_parser = subparsers.add_parser("login", help="Bei der Plattform anmelden")
    login_parser.add_argument("--username", "-u", help="Benutzername")
    login_parser.add_argument("--password", "-p", help="Passwort")
    login_parser.add_argument("--save", action="store_true", help="Anmeldedaten speichern")
    
    ## Posts auflisten
    list_parser = subparsers.add_parser("list", help="Alle Beiträge auflisten")
    list_parser.add_argument("--count", "-c", type=int, default=10, help="Anzahl der anzuzeigenden Beiträge")
    
    ## Einzelnen Post anzeigen
    show_parser = subparsers.add_parser("show", help="Einzelnen Beitrag anzeigen")
    show_parser.add_argument("post_id", help="ID des Beitrags")
    
    ## Neuen Post erstellen
    create_parser = subparsers.add_parser("create", help="Neuen Beitrag erstellen")
    create_parser.add_argument("--title", "-t", required=True, help="Titel des Beitrags")
    create_parser.add_argument("--content", "-c", help="Inhalt des Beitrags")
    create_parser.add_argument("--file", "-f", help="Datei mit Inhalt des Beitrags")
    
    ## Kommentar hinzufügen
    comment_parser = subparsers.add_parser("comment", help="Kommentar zu einem Beitrag hinzufügen")
    comment_parser.add_argument("post_id", help="ID des Beitrags")
    comment_parser.add_argument("--text", "-t", required=True, help="Text des Kommentars")
    
    args = parser.parse_args()
    
    ## Konfiguration laden
    config = load_config()
    
    ## WebScraper-Instanz erstellen
    scraper = WebScraper(config.get("base_url", "https://example.com"))
    
    ## Befehl ausführen
    if args.command == "login":
        username = args.username or input("Benutzername: ")
        password = args.password or input("Passwort: ")
        success = scraper.login(username, password)
        if success:
            print("Login erfolgreich!")
            if args.save:
                ## Speichern der Session (nicht das Passwort)
                scraper.save_session()
        else:
            print("Login fehlgeschlagen!")
            sys.exit(1)
            
    elif args.command == "list":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        posts = scraper.get_posts(args.count)
        if posts:
            print(f"Gefundene Beiträge ({len(posts)}):")
            for post in posts:
                print(f"ID: {post['id']} | Titel: {post['title']} | Datum: {post['date']}")
        else:
            print("Keine Beiträge gefunden.")
            
    elif args.command == "show":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        post = scraper.get_post(args.post_id)
        if post:
            print(f"Titel: {post['title']}")
            print(f"Autor: {post['author']}")
            print(f"Datum: {post['date']}")
            print("\n" + post['content'])
            
            if post.get('comments'):
                print("\nKommentare:")
                for comment in post['comments']:
                    print(f"- {comment['author']} ({comment['date']}): {comment['text']}")
        else:
            print(f"Beitrag mit ID {args.post_id} nicht gefunden.")
            
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
        
        success, post_id = scraper.create_post(args.title, content)
        if success:
            print(f"Beitrag erfolgreich erstellt! ID: {post_id}")
        else:
            print("Fehler beim Erstellen des Beitrags.")
            
    elif args.command == "comment":
        if not scraper.is_logged_in():
            print("Bitte zuerst einloggen mit: login")
            sys.exit(1)
        
        success = scraper.add_comment(args.post_id, args.text)
        if success:
            print("Kommentar erfolgreich hinzugefügt!")
        else:
            print("Fehler beim Hinzufügen des Kommentars.")
            
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
