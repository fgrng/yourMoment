#!/usr/bin/env python3
import argparse
from src.scraper import WebScraper
from src.config import load_config
from src.commands import add_auth_subparsers, add_post_subparsers, add_comment_subparsers, add_monitor_subparsers

def main():
    parser = argparse.ArgumentParser(description="Kommandozeilen-Client für myMoment Schreibplattform")
    subparsers = parser.add_subparsers(dest="command", help="Befehle")
    
    # Befehle aus den Modulen hinzufügen
    add_auth_subparsers(subparsers)
    add_post_subparsers(subparsers)
    add_comment_subparsers(subparsers)
    add_monitor_subparsers(subparsers)
    
    args = parser.parse_args()
    
    # Konfiguration laden
    config = load_config()
    
    # WebScraper-Instanz erstellen
    scraper = WebScraper(config.get("base_url", "https://new.mymoment.ch"))
    
    # Wenn ein Befehl angegeben wurde und der Befehl eine Funktion hat
    if hasattr(args, 'func'):
        args.func(args, scraper)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
