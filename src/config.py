import os
import json

CONFIG_FILE = os.path.expanduser('~/.mymoment_config.json')

def load_config():
    """Lädt die Konfiguration aus der Konfigurationsdatei."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Fehler beim Laden der Konfiguration: {e}")
    
    ## Standardkonfiguration zurückgeben, wenn keine Datei existiert
    return {
        "base_url": "https://new.mymoment.ch"
    }

def save_config(config):
    """Speichert die Konfiguration in der Konfigurationsdatei."""
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Fehler beim Speichern der Konfiguration: {e}")
        return False
