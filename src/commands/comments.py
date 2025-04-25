from src.commands.auth import check_login

def add_comment_subparsers(subparsers):
    """Fügt Kommentar-bezogene Befehle zum Parser hinzu."""
    ## Kommentare eines Beitrags anzeigen
    comments_parser = subparsers.add_parser("comments", help="Kommentare eines Beitrags anzeigen")
    comments_parser.add_argument("post_id", help="ID des Beitrags")
    comments_parser.set_defaults(func=cmd_list_comments)
    
    ## Kommentar hinzufügen
    comment_parser = subparsers.add_parser("comment", help="Kommentar zu einem Beitrag hinzufügen")
    comment_parser.add_argument("post_id", help="ID des Beitrags")
    comment_parser.add_argument("--text", "-t", required=True, help="Text des Kommentars")
    comment_parser.add_argument("--highlight", "-H", help="Hervorgehobener Text im Beitrag")
    comment_parser.set_defaults(func=cmd_add_comment)
    
    ## Kommentar bearbeiten
    edit_comment_parser = subparsers.add_parser("edit-comment", help="Eigenen Kommentar bearbeiten")
    edit_comment_parser.add_argument("comment_id", help="ID des Kommentars")
    edit_comment_parser.add_argument("--text", "-t", required=True, help="Neuer Text des Kommentars")
    edit_comment_parser.set_defaults(func=cmd_edit_comment)

def cmd_list_comments(args, scraper):
    """Führt den Befehl zum Auflisten der Kommentare eines Beitrags aus."""
    check_login(scraper)
    
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

def cmd_add_comment(args, scraper):
    """Führt den Befehl zum Hinzufügen eines Kommentars aus."""
    check_login(scraper)
    
    print(f"Füge Kommentar zu Beitrag {args.post_id} hinzu...")
    success = scraper.add_comment(args.post_id, args.text, args.highlight)
    
    if success:
        print("Kommentar erfolgreich hinzugefügt!")
    else:
        print("Fehler beim Hinzufügen des Kommentars.")

def cmd_edit_comment(args, scraper):
    """Führt den Befehl zum Bearbeiten eines Kommentars aus."""
    check_login(scraper)
    
    print(f"Bearbeite Kommentar mit ID {args.comment_id}...")
    success = scraper.edit_comment(args.comment_id, args.text)
    
    if success:
        print("Kommentar erfolgreich bearbeitet!")
    else:
        print("Fehler beim Bearbeiten des Kommentars.")
