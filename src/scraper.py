import os
import pickle
import requests
from bs4 import BeautifulSoup
import time

class WebScraper:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session = requests.Session()
        self.session_file = os.path.expanduser("~/.writingapp_session")
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
            ## Hier eine Seite prüfen, die nur für eingeloggte Nutzer zugänglich ist
            response = self.session.get(f"{self.base_url}/dashboard", allow_redirects=False)
            return response.status_code == 200
        except Exception:
            return False

    def login(self, username, password):
        """Loggt den Nutzer ein."""
        try:
            ## Zunächst Login-Seite laden, um CSRF-Token oder ähnliches zu extrahieren
            login_page = self.session.get(f"{self.base_url}/login")
            soup = BeautifulSoup(login_page.text, 'html.parser')
            
            ## CSRF-Token suchen (falls vorhanden)
            csrf_token = None
            token_field = soup.find('input', {'name': 'csrf_token'})
            if token_field:
                csrf_token = token_field.get('value')
            
            ## Login-Daten zusammenstellen
            login_data = {
                'username': username,
                'password': password
            }
            
            if csrf_token:
                login_data['csrf_token'] = csrf_token
            
            ## Login durchführen
            response = self.session.post(
                f"{self.base_url}/login",
                data=login_data,
                headers={
                    'Referer': f"{self.base_url}/login",
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            
            ## Erfolg überprüfen
            return self.is_logged_in()
        except Exception as e:
            print(f"Login-Fehler: {e}")
            return False

    def get_posts(self, limit=10):
        """Ruft die Liste der neuesten Beiträge ab."""
        try:
            ## Liste der Beiträge abrufen
            response = self.session.get(f"{self.base_url}/posts")
            soup = BeautifulSoup(response.text, 'html.parser')
            
            posts = []
            ## Beiträge identifizieren und extrahieren
            ## (Die genauen CSS-Selektoren oder HTML-Strukturen müssen 
            ## an die tatsächliche Website angepasst werden)
            post_elements = soup.select('.post-item')[:limit]
            
            for element in post_elements:
                post_id = element.get('data-post-id', '')
                title_element = element.find('h2', class_='post-title')
                date_element = element.find('span', class_='post-date')
                
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
            response = self.session.get(f"{self.base_url}/post/{post_id}")
            soup = BeautifulSoup(response.text, 'html.parser')
            
            ## Post-Details extrahieren
            title = soup.find('h1', class_='post-title').text.strip()
            author = soup.find('span', class_='post-author').text.strip()
            date = soup.find('span', class_='post-date').text.strip()
            content = soup.find('div', class_='post-content').text.strip()
            
            ## Kommentare extrahieren
            comments = []
            comment_elements = soup.select('.comment')
            for comment in comment_elements:
                author_element = comment.find('span', class_='comment-author')
                date_element = comment.find('span', class_='comment-date')
                text_element = comment.find('div', class_='comment-text')
                
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
            ## Formular-Seite laden, um CSRF-Token zu bekommen
            form_page = self.session.get(f"{self.base_url}/create")
            soup = BeautifulSoup(form_page.text, 'html.parser')
            
            ## CSRF-Token extrahieren
            csrf_token = None
            token_field = soup.find('input', {'name': 'csrf_token'})
            if token_field:
                csrf_token = token_field.get('value')
            
            ## Formulardaten zusammenstellen
            post_data = {
                'title': title,
                'content': content
            }
            
            if csrf_token:
                post_data['csrf_token'] = csrf_token
            
            ## Post erstellen
            response = self.session.post(
                f"{self.base_url}/create",
                data=post_data,
                headers={
                    'Referer': f"{self.base_url}/create",
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            
            ## Erfolg prüfen und Post-ID extrahieren
            if response.status_code == 200 or response.status_code == 302:
                ## Bei Erfolg wird oft auf die neue Post-Seite weitergeleitet
                ## Aus der Redirect-URL oder Antwort die Post-ID extrahieren
                if response.status_code == 302:
                    redirect_url = response.headers.get('Location', '')
                    post_id = redirect_url.split('/')[-1]
                else:
                    ## Alternativ: Post-ID aus der Antwort extrahieren
                    soup = BeautifulSoup(response.text, 'html.parser')
                    post_id_element = soup.find('meta', {'name': 'post_id'})
                    post_id = post_id_element.get('content') if post_id_element else 'unknown'
                    
                return True, post_id
            else:
                return False, None
        except Exception as e:
            print(f"Fehler beim Erstellen des Beitrags: {e}")
            return False, None

    def add_comment(self, post_id, text):
        """Fügt einen Kommentar zu einem Beitrag hinzu."""
        try:
            ## Zunächst die Post-Seite laden, um CSRF-Token zu bekommen
            post_page = self.session.get(f"{self.base_url}/post/{post_id}")
            soup = BeautifulSoup(post_page.text, 'html.parser')
            
            ## CSRF-Token extrahieren
            csrf_token = None
            token_field = soup.find('input', {'name': 'csrf_token'})
            if token_field:
                csrf_token = token_field.get('value')
            
            ## Kommentar-Daten zusammenstellen
            comment_data = {
                'post_id': post_id,
                'comment_text': text
            }
            
            if csrf_token:
                comment_data['csrf_token'] = csrf_token
            
            ## Kommentar absenden
            response = self.session.post(
                f"{self.base_url}/comment",
                data=comment_data,
                headers={
                    'Referer': f"{self.base_url}/post/{post_id}",
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            
            ## Erfolg prüfen
            return response.status_code == 200 or response.status_code == 302
        except Exception as e:
            print(f"Fehler beim Hinzufügen des Kommentars: {e}")
            return False
