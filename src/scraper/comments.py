import re
from bs4 import BeautifulSoup

class CommentManager:
    def __init__(self, session_manager, post_manager):
        self.session_manager = session_manager
        self.post_manager = post_manager
        self.base_url = session_manager.base_url
        self.session = session_manager.session

    def add_comment(self, post_id, text, highlight=None, hidden=False):
        """Fügt einen Kommentar zu einem Beitrag hinzu.
        
        Args:
            post_id (str): ID des Beitrags
            text (str): Text des Kommentars
            highlight (str, optional): Hervorgehobener Text im Beitrag
            hidden (bool, optional): Ob der Kommentar versteckt sein soll. Standard ist False.

        Returns:
            bool: True, wenn der Kommentar erfolgreich hinzugefügt wurde, sonst False.
        """
        try:
            ## Zuerst die Detailseite des Beitrags laden, um das CSRF-Token zu bekommen
            post = self.post_manager.get_post(post_id)
            if not post or not post.get('csrf_token'):
                print("Konnte CSRF-Token nicht finden, um Kommentar hinzuzufügen.")
                return False
            
            ## Kommentar-URL für diesen Beitrag
            comment_url = f"{self.base_url}/article/{post_id}/comment/"
            
            ## Kommentar-Daten zusammenstellen
            comment_data = {
                'csrfmiddlewaretoken': post['csrf_token'],
                'text': text,
                'status': '20',  ## 20 = Publiziert (aus dem HTML erkennbar)
                'highlight': highlight or ''   ## Optional: Text-Hervorhebung
            }

            ## Verstecken-Option hinzufügen, falls aktiviert
            if hidden:
                comment_data['hide'] = 'on'
            
            ## Kommentar absenden
            response = self.session.post(
                comment_url,
                data=comment_data,
                headers={
                    'Referer': post['url'],
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            
            ## Erfolg prüfen
            return response.status_code == 200 or response.status_code == 302
        except Exception as e:
            print(f"Fehler beim Hinzufügen des Kommentars: {e}")
            return False

    def get_comments(self, post_id):
        """Ruft alle Kommentare eines Beitrags ab."""
        post = self.post_manager.get_post(post_id)
        if not post:
            print(f"Beitrag mit ID {post_id} nicht gefunden.")
            return []
        
        return post.get('comments', [])

    def edit_comment(self, comment_id, text):
        """Bearbeitet einen eigenen Kommentar."""
        try:
            ## Kommentar-Bearbeitungsseite laden
            edit_url = f"{self.base_url}/comment/{comment_id}/"
            edit_page = self.session.get(edit_url)
            
            soup = BeautifulSoup(edit_page.text, 'html.parser')
            
            ## CSRF-Token extrahieren
            csrf_token = None
            csrf_input = soup.find('input', {'name': 'csrfmiddlewaretoken'})
            if csrf_input:
                csrf_token = csrf_input.get('value')
            else:
                print("Konnte CSRF-Token nicht finden, um Kommentar zu bearbeiten.")
                return False
            
            ## Kommentar-Daten zusammenstellen
            comment_data = {
                'csrfmiddlewaretoken': csrf_token,
                'text': text,
                'status': '20',  ## 20 = Publiziert (Standard)
            }
            
            ## Kommentar aktualisieren
            response = self.session.post(
                edit_url,
                data=comment_data,
                headers={
                    'Referer': edit_url,
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            
            ## Erfolg prüfen
            return response.status_code == 200 or response.status_code == 302
        except Exception as e:
            print(f"Fehler beim Bearbeiten des Kommentars: {e}")
            return False
