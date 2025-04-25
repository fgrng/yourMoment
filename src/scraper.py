import os
import pickle
import requests
from bs4 import BeautifulSoup
import time
import re

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
                    self.save_session()
                    return True
            
            return False
        except Exception as e:
            print(f"Login-Fehler: {e}")
            return False

    def get_posts(self, limit=10, tab="home"):
        """Ruft die Liste der neuesten Beiträge ab.
        
        Args:
            limit: Maximale Anzahl der abzurufenden Beiträge
            tab: Welcher Tab soll abgerufen werden ('home' für "Meine", 'alle' für "Alle",
                 oder die ID eines Klassenraums)
        """
        try:
            ## Übersichtsseite mit Beiträgen laden
            response = self.session.get(f"{self.base_url}/articles/")
            soup = BeautifulSoup(response.text, 'html.parser')
            
            ## Den entsprechenden Tab basierend auf dem Parameter auswählen
            tab_id = f"pills-{tab}"
            tab_content = soup.find('div', {'id': tab_id})
            
            if not tab_content:
                print(f"Tab '{tab}' nicht gefunden.")
                return []
            
            posts = []
            ## Beitragskarten aus dem ausgewählten Tab extrahieren
            post_cards = tab_content.select('.col-xl-4.mb-4')[:limit]
            
            for card in post_cards:
                ## Link zum Beitrag extrahieren, der die ID enthält
                link_element = card.find('a')
                if not link_element:
                    continue
                
                href = link_element.get('href', '')
                post_id = None
                ## ID aus URL extrahieren
                if '/article/' in href:
                    post_id = href.strip('/').split('/')[-1]
                elif '/article/edit/' in href:
                    post_id = href.strip('/').split('/')[-1]
                
                ## Titel extrahieren
                title_element = card.find('div', class_='article-title')
                title = title_element.text.strip() if title_element else 'Unbekannter Titel'
                
                ## Autor extrahieren
                author_element = card.find('div', class_='article-author')
                author = author_element.text.strip() if author_element else 'Unbekannter Autor'
                
                ## Datum extrahieren
                date_element = card.find('div', class_='article-date')
                date = date_element.text.strip() if date_element else 'Unbekanntes Datum'
                
                ## Status ermitteln (Entwurf, Lehrpersonenkontrolle, Publiziert)
                status_element = card.find('div', class_=re.compile(r'card-header\s+\w+'))
                status = 'Unbekannt'
                if status_element:
                    for class_name in status_element.get('class', []):
                        if class_name in ['entwurf', 'lehrpersonenkontrolle', 'publiziert']:
                            status = class_name.capitalize()
                
                ## Sichtbar für welche Klasse/Gruppe
                visibility_element = card.find('div', class_='article-classroom')
                visibility = visibility_element.text.strip() if visibility_element else 'Unbekannt'
                
                ## Bild URL extrahieren
                img_element = card.find('div', class_='card-body').find('img')
                img_url = img_element.get('src') if img_element else None
                
                posts.append({
                    'id': post_id,
                    'title': title,
                    'author': author,
                    'date': date,
                    'status': status,
                    'visibility': visibility,
                    'img_url': img_url,
                    'url': f"{self.base_url}{href}" if href.startswith('/') else href
                })
            
            return posts
        except Exception as e:
            print(f"Fehler beim Abrufen der Beiträge: {e}")
            return []

    def get_post(self, post_id):
        """Ruft einen einzelnen Beitrag mit der angegebenen ID ab."""
        try:
            ## URL für einzelnen Beitrag
            response = self.session.get(f"{self.base_url}/article/{post_id}/")
            
            ## Prüfen ob wir zur Edit-Seite weitergeleitet wurden (z.B. bei eigenen Entwürfen)
            if '/article/edit/' in response.url:
                return self.get_post_edit(post_id)
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            ## Struktur basierend auf der tatsächlichen Beitragsseite extrahieren
            ## Dies muss angepasst werden, wenn wir das tatsächliche HTML der Beitragsseite sehen
            
            ## Vermutlich hat die Seite einen Titel, Autor, Datum und Inhalt
            title = 'Unbekannter Titel'
            title_element = soup.find('h1')
            if title_element:
                title = title_element.text.strip()
            
            ## Autor und Datum sind wahrscheinlich in bestimmten Klassen oder Elementen
            author = 'Unbekannter Autor'
            author_element = soup.find('div', class_='article-author')
            if author_element:
                author = author_element.text.strip()
            
            date = 'Unbekanntes Datum'
            date_element = soup.find('div', class_='article-date')
            if date_element:
                date = date_element.text.strip()
            
            ## Inhalt des Beitrags
            content = 'Kein Inhalt verfügbar'
            content_element = soup.find('div', class_='article-content')
            if content_element:
                content = content_element.text.strip()
            
            ## Kommentare extrahieren, falls vorhanden
            comments = []
            comment_elements = soup.select('.comment')
            for comment in comment_elements:
                comment_author_element = comment.find(class_='comment-author')
                comment_date_element = comment.find(class_='comment-date')
                comment_text_element = comment.find(class_='comment-text')
                
                comments.append({
                    'author': comment_author_element.text.strip() if comment_author_element else 'Unbekannt',
                    'date': comment_date_element.text.strip() if comment_date_element else 'Unbekannt',
                    'text': comment_text_element.text.strip() if comment_text_element else 'Kein Text'
                })
            
            return {
                'id': post_id,
                'title': title,
                'author': author,
                'date': date,
                'content': content,
                'comments': comments,
                'url': f"{self.base_url}/article/{post_id}/"
            }
        except Exception as e:
            print(f"Fehler beim Abrufen des Beitrags: {e}")
            return None

    def get_post_edit(self, post_id):
        """Ruft einen Beitrag im Bearbeitungsmodus ab."""
        try:
            ## URL für Edit-Modus
            response = self.session.get(f"{self.base_url}/article/edit/{post_id}/")
            soup = BeautifulSoup(response.text, 'html.parser')
            
            ## Struktur für den Edit-Modus (vermutlich ein Formular)
            title = 'Unbekannter Titel'
            title_element = soup.find('input', {'name': 'title'})
            if title_element:
                title = title_element.get('value', 'Unbekannter Titel')
            
            ## Content ist vermutlich in einem Textarea-Element
            content = 'Kein Inhalt verfügbar'
            content_element = soup.find('textarea', {'name': 'content'})
            if content_element:
                content = content_element.text.strip()
            
            ## Autor und Datum sind möglicherweise woanders oder nicht verfügbar im Edit-Modus
            author = 'Eigener Beitrag'
            date = 'In Bearbeitung'
            
            return {
                'id': post_id,
                'title': title,
                'author': author,
                'date': date,
                'content': content,
                'comments': [],  ## Im Edit-Modus wahrscheinlich keine Kommentare sichtbar
                'url': f"{self.base_url}/article/edit/{post_id}/",
                'is_edit_mode': True
            }
        except Exception as e:
            print(f"Fehler beim Abrufen des Beitrags im Edit-Modus: {e}")
            return None

    def create_post(self, title, content, category_id=None):
        """Erstellt einen neuen Beitrag."""
        try:
            ## Formular-Seite für neuen Beitrag laden
            form_url = f"{self.base_url}/article/create/"
            form_page = self.session.get(form_url)
            soup = BeautifulSoup(form_page.text, 'html.parser')
            
            ## CSRF-Token extrahieren
            csrf_token = soup.find('input', {'name': 'csrfmiddlewaretoken'}).get('value')
            
            ## Formulardaten zusammenstellen
            post_data = {
                'csrfmiddlewaretoken': csrf_token,
                'title': title,
                'content': content,
            }
            
            ## Kategorie hinzufügen, falls angegeben
            if category_id:
                post_data['category'] = category_id
            
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
                ## Bei Erfolg werden wir vermutlich zur Edit-Seite weitergeleitet
                if '/article/edit/' in response.url:
                    ## Post-ID aus der URL extrahieren
                    post_id = response.url.strip('/').split('/')[-1]
                    return True, post_id
                ## Oder zur Ansichtsseite, wenn der Post direkt veröffentlicht wurde
                elif '/article/' in response.url:
                    post_id = response.url.strip('/').split('/')[-1]
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
            ## Beitragsseite laden, um CSRF-Token zu bekommen
            post_url = f"{self.base_url}/article/{post_id}/"
            post_page = self.session.get(post_url)
            soup = BeautifulSoup(post_page.text, 'html.parser')
            
            ## CSRF-Token extrahieren
            csrf_token = soup.find('input', {'name': 'csrfmiddlewaretoken'}).get('value')
            
            ## Kommentar-Formulardaten
            ## Die genauen Feldnamen müssen angepasst werden, sobald das tatsächliche Formular bekannt ist
            comment_data = {
                'csrfmiddlewaretoken': csrf_token,
                'comment_text': text  ## Name des Feldes könnte anders sein
            }
            
            ## Kommentar-URL könnte variieren
            comment_url = f"{self.base_url}/article/{post_id}/comment/"
            
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

    def get_categories(self):
        """Ruft die verfügbaren Kategorien ab."""
        try:
            ## Beitragsübersicht laden, wo die Kategorien als Dropdown angezeigt werden
            response = self.session.get(f"{self.base_url}/articles/")
            soup = BeautifulSoup(response.text, 'html.parser')
            
            categories = []
            ## Kategorie-Dropdown finden
            category_select = soup.find('select', {'name': 'kategorie'})
            if category_select:
                for option in category_select.find_all('option'):
                    ## Option mit Wert 'Alle Kategorien' überspringen
                    if option.get('value') == '':
                        continue
                    
                    category_id = option.get('value')
                    category_name = option.text.strip()
                    categories.append({
                        'id': category_id,
                        'name': category_name
                    })
            
            return categories
        except Exception as e:
            print(f"Fehler beim Abrufen der Kategorien: {e}")
            return []
