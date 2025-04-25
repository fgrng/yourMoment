import os
import pickle
import requests
from bs4 import BeautifulSoup

class SessionManager:
    def __init__(self, base_url="https://new.mymoment.ch"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session_file = os.path.expanduser("~/.mymoment_session")
        self._load_session()

    def _load_session(self):
        """Lädt eine gespeicherte Session, falls vorhanden."""
        if os.path.exists(self.session_file):
            try:
                with open(self.session_file, 'rb') as f:
                    self.session.cookies.update(pickle.load(f))
                return True
            except Exception:
                return False
        return False

    def save_session(self):
        """Speichert die aktuelle Session."""
        os.makedirs(os.path.dirname(self.session_file), exist_ok=True)
        with open(self.session_file, 'wb') as f:
            pickle.dump(self.session.cookies, f)

    def is_logged_in(self):
        """Überprüft, ob der Nutzer eingeloggt ist."""
        try:
            ## Bei myMoment schauen wir nach, ob auf der Hauptseite ein Abmelden-Button vorhanden ist
            response = self.session.get(f"{self.base_url}/")
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                ## Suche nach dem Abmelden-Button, der nur für eingeloggte Benutzer sichtbar ist
                logout_form = soup.find('form', attrs={'action': '/accounts/logout/'})
                return logout_form is not None
            return False
        except Exception as e:
            print(f"Fehler bei der Login-Überprüfung: {e}")
            return False

    def login(self, username, password):
        """Loggt den Nutzer in myMoment ein."""
        try:
            ## Login-Seite laden, um CSRF-Token zu erhalten
            login_url = f"{self.base_url}/accounts/login/"
            login_page = self.session.get(login_url)
            soup = BeautifulSoup(login_page.text, 'html.parser')
            
            ## CSRF-Token extrahieren
            csrf_token = soup.find('input', {'name': 'csrfmiddlewaretoken'}).get('value')
            
            ## Login-Daten zusammenstellen
            login_data = {
                'csrfmiddlewaretoken': csrf_token,
                'username': username,
                'password': password,
                'next': ''  ## aus dem Formular ersichtlich
            }
            
            ## Login durchführen
            response = self.session.post(
                login_url,
                data=login_data,
                headers={
                    'Referer': login_url,
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            
            ## Erfolg überprüfen
            if response.status_code == 200 or response.status_code == 302:
                ## Session speichern bei erfolgreicher Anmeldung
                if self.is_logged_in():
                    return True
            
            return False
        except Exception as e:
            print(f"Login-Fehler: {e}")
            return False
