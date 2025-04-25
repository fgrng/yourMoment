import argparse
import sys
from src.scraper import WebScraper

def add_auth_subparsers(subparsers):
    """Fügt Authentifizierungs-bezogene Befehle zum Parser hinzu."""
    ## Login-Befehl
    login_parser = subparsers.add_parser("login", help="Bei der Plattform anmelden")
    login_parser.add_argument("--username", "-u", help="Benutzername")
    login_parser.add_argument("--password", "-p", help="Passwort")
    login_parser.add_argument("--save", action="store_true", help="Anmeldedaten speichern")
    login_parser.set_defaults(func=cmd_login)

def cmd_login(args, scraper):
    """Führt den Login-Befehl aus."""
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

def check_login(scraper):
    """Überprüft, ob der Benutzer eingeloggt ist und beendet das Programm, falls nicht."""
    if not scraper.is_logged_in():
        print("Bitte zuerst einloggen mit: login")
        sys.exit(1)
