import os
import pickle
import requests
from bs4 import BeautifulSoup
import time

class WebScraper:
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
            ## Bei myMoment schauen wir nach, ob wir auf die Hauptseite zugreifen können
            ## ohne auf die Login-Seite umgeleitet zu werden
            response = self.session.get(f"{self.base_url}/", allow_redirects=False)
            
            ## Wenn wir eingeloggt sind, sollten wir auf der Hauptseite bleiben
            ## und es sollte ein Benutzername oder ein Logout-Link sichtbar sein
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                ## Suche nach typischen Elementen einer eingeloggten Session
                ## Dies muss angepasst werden, basierend auf dem Aussehen der eingeloggten Seite
                logout_link = soup.find('a', href='/accounts/logout/')
                return logout_link is not None
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
            
            ## CSRF-Token extrahieren (aus dem HTML erkennbar)
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

    def get_posts(self, limit=10):
        """Ruft die Liste der neuesten Beiträge ab."""
        try:
            ## Vermutlich gibt es eine Übersichtsseite mit Beiträgen
            ## Da das genaue URL-Muster nicht bekannt ist, verwenden wir eine Annahme
            response = self.session.get(f"{self.base_url}/posts/")
            soup = BeautifulSoup(response.text, 'html.parser')
            
            posts = []
            ## Da wir die genaue HTML-Struktur der Beitragsliste nicht kennen,
            ## verwenden wir eine generische Suche, die angepasst werden muss
            ## Diese Selektoren müssen an die tatsächliche Website angepasst werden
            post_elements = soup.select('.article-item')[:limit]
            
            for element in post_elements:
                post_id = element.get('id', '').replace('post-', '')
                title_element = element.find('h2') or element.find('h3')
                date_element = element.find('time') or element.find('.post-date')
                
                posts.append({
                    'id': post_id,
                    'title': title_element.text.strip() if title_element else 'Unbekannter Titel',
                    'date': date_element.text.strip() if date_element else 'Unbekanntes Datum'
                })
            
            return posts
        except Exception as e:
            print(f"Fehler beim Abrufen der Beiträge: {e}")
            return []

    def get_post(self, post_id):
        """Ruft einen einzelnen Beitrag mit der angegebenen ID ab."""
        try:
            ## Annahme des URL-Musters, muss angepasst werden
            response = self.session.get(f"{self.base_url}/post/{post_id}/")
            soup = BeautifulSoup(response.text, 'html.parser')
            
            ## Diese Selektoren müssen an die tatsächliche Website angepasst werden
            title = soup.find('h1').text.strip() if soup.find('h1') else 'Unbekannter Titel'
            author = soup.find('.post-author').text.strip() if soup.find('.post-author') else 'Unbekannter Autor'
            date = soup.find('time').text.strip() if soup.find('time') else 'Unbekanntes Datum'
            content_element = soup.find('.post-content') or soup.find('article')
            content = content_element.text.strip() if content_element else 'Kein Inhalt verfügbar'
            
            ## Kommentare extrahieren
            comments = []
            comment_elements = soup.select('.comment')
            for comment in comment_elements:
                author_element = comment.find('.comment-author')
                date_element = comment.find('.comment-date') or comment.find('time')
                text_element = comment.find('.comment-text') or comment.find('.comment-content')
                
                comments.append({
                    'author': author_element.text.strip() if author_element else 'Unbekannt',
                    'date': date_element.text.strip() if date_element else '',
                    'text': text_element.text.strip() if text_element else ''
                })
            
            return {
                'id': post_id,
                'title': title,
                'author': author,
                'date': date,
                'content': content,
                'comments': comments
            }
        except Exception as e:
            print(f"Fehler beim Abrufen des Beitrags: {e}")
            return None

    def create_post(self, title, content):
        """Erstellt einen neuen Beitrag."""
        try:
            ## Annahme des URL-Musters für die Erstellungsseite
            form_url = f"{self.base_url}/create/"
            form_page = self.session.get(form_url)
            soup = BeautifulSoup(form_page.text, 'html.parser')
            
            ## CSRF-Token extrahieren
            csrf_token = soup.find('input', {'name': 'csrfmiddlewaretoken'}).get('value')
            
            ## Annahme der Formulardaten, muss angepasst werden
            post_data = {
                'csrfmiddlewaretoken': csrf_token,
                'title': title,
                'content': content
                ## Hier könnten weitere Felder erforderlich sein
            }
            
            ## Post erstellen
            response = self.session.post(
                form_url,
                data=post_data,
                headers={
                    'Referer': form_url,
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            
            ## Erfolg prüfen und Post-ID extrahieren
            if response.status_code == 200 or response.status_code == 302:
                ## Bei Erfolg wird oft auf die neue Post-Seite weitergeleitet
                ## Aus der Redirect-URL oder Antwort die Post-ID extrahieren
                if response.url != form_url:
                    ## Versuchen, die Post-ID aus der URL zu extrahieren
                    post_id = response.url.rstrip('/').split('/')[-1]
                    return True, post_id
                return True, 'unknown'
            else:
                return False, None
        except Exception as e:
            print(f"Fehler beim Erstellen des Beitrags: {e}")
            return False, None

    def add_comment(self, post_id, text):
        """Fügt einen Kommentar zu einem Beitrag hinzu."""
        try:
            ## Annahme des URL-Musters für die Post-Seite
            post_url = f"{self.base_url}/post/{post_id}/"
            post_page = self.session.get(post_url)
            soup = BeautifulSoup(post_page.text, 'html.parser')
            
            ## CSRF-Token extrahieren
            csrf_token = soup.find('input', {'name': 'csrfmiddlewaretoken'}).get('value')
            
            ## Annahme der Kommentar-Formulardaten
            comment_data = {
                'csrfmiddlewaretoken': csrf_token,
                'comment': text
                ## Hier könnten weitere Felder erforderlich sein
            }
            
            ## Annahme des URL-Musters für das Kommentar-Formular
            comment_url = f"{self.base_url}/post/{post_id}/comment/"
            
            ## Kommentar absenden
            response = self.session.post(
                comment_url,
                data=comment_data,
                headers={
                    'Referer': post_url,
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            
            ## Erfolg prüfen
            return response.status_code == 200 or response.status_code == 302
        except Exception as e:
            print(f"Fehler beim Hinzufügen des Kommentars: {e}")
            return False
