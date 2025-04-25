import re
from bs4 import BeautifulSoup

class PostManager:
    def __init__(self, session_manager):
        self.session_manager = session_manager
        self.base_url = session_manager.base_url
        self.session = session_manager.session


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
            
            ## Prüfen, ob der Beitrag dem aktuellen Benutzer gehört
            is_own_post = False
            edit_button = soup.find('button', {'data-bs-target': '##edit_article_modal'})
            draft_button = soup.find('button', {'data-bs-target': '##draft_article_modal'})
            if edit_button or draft_button:
                is_own_post = True
            
            ## Titel extrahieren - basierend auf der Detailseite
            title = 'Unbekannter Titel'
            title_element = soup.find('h1')
            if title_element:
                title = title_element.text.strip()
                
                ## Autor aus dem Titel extrahieren, falls er im Format "Titel von Autor" ist
                if ' von ' in title:
                    parts = title.split(' von ')
                    title = parts[0].strip()
                    author = parts[1].strip()
                else:
                    author = 'Unbekannter Autor'
            else:
                author = 'Unbekannter Autor'
            
            ## Datum extrahieren 
            date = 'Unbekanntes Datum'
            date_element = soup.find('h6', class_='d-flex')
            if date_element:
                date_text = date_element.get_text().strip()
                if 'Letzte Aktualisierung:' in date_text:
                    date = date_text.split('Letzte Aktualisierung:')[1].strip().split('\n')[0]
            
            ## Inhalt des Beitrags extrahieren
            content = ''
            content_elements = soup.select('.article .highlight-target p')
            if content_elements:
                content = '\n'.join([el.text.strip() for el in content_elements])
            else:
                ## Alternative: Versuch den Text aus dem Text-to-Speech Bereich zu extrahieren
                tts_element = soup.find('textarea', {'id': 'text-to-speech'})
                if tts_element:
                    content = tts_element.text.strip()
            
            ## Social Stats (Likes, Views) extrahieren
            stats = {}
            social_items = soup.select('.social .list-group-item')
            for item in social_items:
                text = item.text.strip()
                if ':' in text:
                    key, value = text.split(':')
                    stats[key.strip()] = value.strip()
            
            ## Status-Info extrahieren
            status = 'Unbekannt'
            status_alert = soup.find('div', class_='alert')
            if status_alert:
                status_text = status_alert.text.strip()
                if 'sichtbar' in status_text.lower():
                    status = 'Publiziert'
                elif 'entwurf' in status_text.lower():
                    status = 'Entwurf'
            
            ## Kommentare extrahieren
            comments = self.get_comments_from_html(soup)
            
            ## Kommentarformular für CSRF-Token
            csrf_token = None
            comment_form = soup.find('form', {'action': re.compile(r'/article/\d+/comment/')})
            if comment_form:
                csrf_input = comment_form.find('input', {'name': 'csrfmiddlewaretoken'})
                if csrf_input:
                    csrf_token = csrf_input.get('value')
            
            return {
                'id': post_id,
                'title': title,
                'author': author,
                'date': date,
                'content': content,
                'stats': stats,
                'status': status,
                'is_own_post': is_own_post,
                'comments': comments,
                'csrf_token': csrf_token,
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
            
            ## Formular-Elemente für den Edit-Modus extrahieren
            title = 'Unbekannter Titel'
            title_element = soup.find('input', {'name': 'title'})
            if title_element:
                title = title_element.get('value', 'Unbekannter Titel')
            
            ## Content ist vermutlich in einem Textarea-Element
            content = 'Kein Inhalt verfügbar'
            content_element = soup.find('textarea', {'name': 'content'})
            if content_element:
                content = content_element.text.strip()
            
            ## Kategorie
            category_id = None
            category_name = None
            category_select = soup.find('select', {'name': 'category'})
            if category_select:
                selected_option = category_select.find('option', selected=True)
                if selected_option:
                    category_id = selected_option.get('value')
                    category_name = selected_option.text.strip()
            
            ## Status (Entwurf, Publiziert)
            status_id = None
            status_name = None
            status_select = soup.find('select', {'name': 'status'})
            if status_select:
                selected_option = status_select.find('option', selected=True)
                if selected_option:
                    status_id = selected_option.get('value')
                    status_name = selected_option.text.strip()
            
            ## CSRF-Token extrahieren
            csrf_token = None
            csrf_input = soup.find('input', {'name': 'csrfmiddlewaretoken'})
            if csrf_input:
                csrf_token = csrf_input.get('value')
            
            return {
                'id': post_id,
                'title': title,
                'content': content,
                'category': {
                    'id': category_id,
                    'name': category_name
                } if category_id else None,
                'status': {
                    'id': status_id,
                    'name': status_name
                } if status_id else None,
                'csrf_token': csrf_token,
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
                'status': '10'  ## 10 = Entwurf (Standard)
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

    def update_post(self, post_id, title=None, content=None, category_id=None, status_id=None):
        """Aktualisiert einen bestehenden Beitrag."""
        try:
            ## Zuerst den Beitrag im Edit-Modus laden, um die aktuellen Werte zu erhalten
            post = self.get_post_edit(post_id)
            if not post or not post.get('csrf_token'):
                print("Konnte Beitrag nicht im Edit-Modus laden.")
                return False
            
            ## Formulardaten zusammenstellen mit Standardwerten aus dem bestehenden Post
            post_data = {
                'csrfmiddlewaretoken': post['csrf_token'],
                'title': title if title is not None else post['title'],
                'content': content if content is not None else post['content'],
                'status': status_id if status_id is not None else (
                    post['status']['id'] if post.get('status') and post['status'].get('id') else '10'
                )
            }
            
            ## Kategorie hinzufügen, falls angegeben
            if category_id is not None:
                post_data['category'] = category_id
            elif post.get('category') and post['category'].get('id'):
                post_data['category'] = post['category']['id']
            
            ## Post aktualisieren
            update_url = f"{self.base_url}/article/edit/{post_id}/"
            response = self.session.post(
                update_url,
                data=post_data,
                headers={
                    'Referer': update_url,
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            
            ## Erfolg prüfen
            return response.status_code == 200 or response.status_code == 302
        except Exception as e:
            print(f"Fehler beim Aktualisieren des Beitrags: {e}")
            return False

    def publish_post(self, post_id):
        """Veröffentlicht einen Beitrag."""
        try:
            publish_url = f"{self.base_url}/article/{post_id}/publish/"
            response = self.session.get(publish_url, allow_redirects=True)
            return response.status_code == 200 or response.status_code == 302
        except Exception as e:
            print(f"Fehler beim Veröffentlichen des Beitrags: {e}")
            return False

    def draft_post(self, post_id):
        """Zieht einen Beitrag zurück (als Entwurf markieren)."""
        try:
            draft_url = f"{self.base_url}/article/{post_id}/draft/"
            response = self.session.get(draft_url, allow_redirects=True)
            return response.status_code == 200 or response.status_code == 302
        except Exception as e:
            print(f"Fehler beim Zurückziehen des Beitrags: {e}")
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
            
    def like_post(self, post_id):
        """Fügt einen 'Gefällt mir' zu einem Beitrag hinzu."""
        try:
            ## Zuerst die Detailseite des Beitrags laden, um das CSRF-Token zu bekommen
            post = self.get_post(post_id)
            if not post or not post.get('csrf_token'):
                print("Konnte CSRF-Token nicht finden, um 'Gefällt mir' hinzuzufügen.")
                return False
            
            ## Like-URL für diesen Beitrag
            like_url = f"{self.base_url}/article/{post_id}/increment_likes/"
            
            ## Like-Daten zusammenstellen
            like_data = {
                'csrfmiddlewaretoken': post['csrf_token']
            }
            
            ## Like absenden
            response = self.session.post(
                like_url,
                data=like_data,
                headers={
                    'Referer': post['url'],
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            
            ## Erfolg prüfen
            return response.status_code == 200 or response.status_code == 302
        except Exception as e:
            print(f"Fehler beim Hinzufügen von 'Gefällt mir': {e}")
            return False

    def get_comments_from_html(self, soup):
        """Extrahiert Kommentare aus der HTML-Struktur."""
        comments = []
        comment_elements = soup.select('.comment')
        for comment in comment_elements:
            card = comment.find('div', class_='card')
            if not card:
                continue
                
            ## Autor des Kommentars
            author_element = card.find('h5', class_='card-title')
            author = 'Unbekannter Autor'
            if author_element:
                author_text = author_element.get_text().strip()
                if 'von ' in author_text:
                    author = author_text.split('von ')[1].strip()
            
            ## Datum des Kommentars
            date_element = card.find('h6', class_='card-subtitle')
            date = date_element.text.strip() if date_element else 'Unbekanntes Datum'
            
            ## Text des Kommentars
            text_element = card.find('span', class_='card-text')
            text = ''
            if text_element:
                ## Text aus allen p-Elementen extrahieren
                text_paragraphs = text_element.find_all('p')
                if text_paragraphs:
                    text = '\n'.join([p.text.strip() for p in text_paragraphs])
                else:
                    text = text_element.text.strip()
            
            ## Kommentar-ID (z.B. für Bearbeiten)
            comment_id = None
            edit_link = card.find('a', {'href': re.compile(r'/comment/\d+/')})
            if edit_link:
                href = edit_link.get('href', '')
                comment_id = href.strip('/').split('/')[-1]
            
            ## Texthervorhebung
            highlight = None
            highlight_div = comment.find('div', {'id': re.compile(r'highlight-\d+')})
            if highlight_div:
                highlight = highlight_div.text.strip()
                
                ## ID der Hervorhebung
                highlight_id = None
                if highlight_div.get('id'):
                    highlight_id = highlight_div.get('id').replace('highlight-', '')
            
            comments.append({
                'id': comment_id,
                'author': author,
                'date': date,
                'text': text,
                'highlight': highlight,
                'highlight_id': highlight_id if highlight else None,
                'can_edit': edit_link is not None
            })
        
        return comments
