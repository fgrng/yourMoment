import time
import os
import json
import logging
from datetime import datetime

class PostMonitor:
    """Überwacht myMoment nach neuen Beiträgen und kommentiert sie automatisch."""
    
    def __init__(self, web_scraper, config_dir=None):
        self.scraper = web_scraper
        self.running = False
        
        ## Konfigurationsverzeichnis (standardmäßig ~/.mymoment/)
        if config_dir is None:
            self.config_dir = os.path.expanduser('~/.mymoment/')
        else:
            self.config_dir = config_dir
            
        ## Datei zum Speichern der bereits kommentierten Beiträge
        self.commented_posts_file = os.path.join(self.config_dir, 'commented_posts.json')
        
        ## Sicherstellen, dass das Verzeichnis existiert
        os.makedirs(self.config_dir, exist_ok=True)
        
        ## Logger einrichten
        self.logger = logging.getLogger('mymoment.monitor')
        self.logger.setLevel(logging.INFO)
        
        ## Datei-Handler für Logs
        log_file = os.path.join(self.config_dir, 'monitor.log')
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(file_handler)
        
        ## Konsolen-Handler für Logs
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(console_handler)
        
        ## Bereits kommentierte Beiträge laden
        self.commented_posts = self.load_commented_posts()
        
    def load_commented_posts(self):
        """Lädt die Liste der bereits kommentierten Beiträge."""
        if os.path.exists(self.commented_posts_file):
            try:
                with open(self.commented_posts_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"Fehler beim Laden der kommentierten Beiträge: {e}")
        
        ## Standardstruktur zurückgeben, wenn keine Datei existiert
        return {
            "posts": {},
            "last_check": None
        }
    
    def save_commented_posts(self):
        """Speichert die Liste der kommentierten Beiträge."""
        try:
            with open(self.commented_posts_file, 'w', encoding='utf-8') as f:
                json.dump(self.commented_posts, f, indent=2)
            return True
        except Exception as e:
            self.logger.error(f"Fehler beim Speichern der kommentierten Beiträge: {e}")
            return False
    
    def has_commented(self, post_id):
        """Prüft, ob ein Beitrag bereits kommentiert wurde."""
        return post_id in self.commented_posts["posts"]
    
    def mark_as_commented(self, post_id, comment_text=None):
        """Markiert einen Beitrag als kommentiert."""
        self.commented_posts["posts"][post_id] = {
            "commented_at": datetime.now().isoformat(),
            "comment_text": comment_text
        }
        self.save_commented_posts()
    
    def monitor(self, interval=300, tab="alle", category=0, commenter=None, max_posts=20, max_runtime=None, dry_run=False):
        """
        Startet die Überwachung nach neuen Beiträgen.
        
        Args:
            interval: Zeitintervall zwischen den Prüfungen in Sekunden (Standard: 300)
            tab: Welcher Tab soll überwacht werden (Standard: "alle")
            commenter: Instanz einer Kommentierer-Klasse (Standard: None)
            max_posts: Maximale Anzahl der zu prüfenden Beiträge pro Durchlauf (Standard: 20)
            max_runtime: Maximale Laufzeit in Sekunden, None für unbegrenzt (Standard: None)
        """
        if not commenter:
            comment_text = "Interessanter Beitrag! Danke fürs Teilen."
            
        ## Überprüfen, ob der Benutzer eingeloggt ist
        if not self.scraper.is_logged_in():
            self.logger.error("Nicht eingeloggt. Bitte zuerst einloggen.")
            return False
            
        self.running = True
        self.logger.info(f"Starte Überwachung im Tab '{tab}', Intervall: {interval} Sekunden")
        
        start_time = time.time()
        try:
            while self.running:
                ## Maximale Laufzeit prüfen
                if max_runtime and (time.time() - start_time) > max_runtime:
                    self.logger.info(f"Maximale Laufzeit von {max_runtime} Sekunden erreicht. Beende Überwachung.")
                    break
                    
                ## Aktuelle Zeit als letzter Check speichern
                self.commented_posts["last_check"] = datetime.now().isoformat()
                self.save_commented_posts()
                
                ## Neueste Beiträge abrufen
                self.logger.info(f"Suche nach neuen Beiträgen im Tab '{tab}'...")
                posts = self.scraper.get_posts(max_posts, tab)

                ## Reduziere auf Beiträge der Kategorie
                if not (category == 0):
                    posts = [post for post in posts if post.get('category_id') == category]
                
                if not posts:
                    self.logger.warning("Keine Beiträge gefunden.")
                else:
                    self.logger.info(f"{len(posts)} Beiträge gefunden. Prüfe auf neue Beiträge...")
                    new_post_count = 0
                    
                    for post in posts:
                        post_id = post.get('id')
                        if not post_id:
                            continue
                            
                        ## Prüfen, ob bereits kommentiert
                        if not self.has_commented(post_id):
                            ## Neuen Beitrag gefunden - Kommentar erstellen
                            self.logger.info(f"Neuer Beitrag gefunden: {post.get('title')} (ID: {post_id})")
                            
                            ## Personalisieren des Kommentars falls gewünscht
                            comment_text = commenter.generate_comment(post)
                            
                            ## Kommentar hinzufügen
                            if not dry_run:
                                success = self.scraper.add_comment(post_id, comment_text)

                            if dry_run or success:
                                self.logger.info(f"Kommentar zu Beitrag {post_id} erfolgreich hinzugefügt (dry-run)")
                                self.mark_as_commented(post_id, comment_text)
                                new_post_count += 1
                            else:
                                self.logger.error(f"Fehler beim Hinzufügen des Kommentars zu Beitrag {post_id}")
                    
                    self.logger.info(f"{new_post_count} neue Beiträge kommentiert")
                
                ## Warten bis zum nächsten Durchlauf
                self.logger.info(f"Warte {interval} Sekunden bis zur nächsten Prüfung...")
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self.logger.info("Überwachung durch Benutzer beendet (Tastatur-Unterbrechung)")
        except Exception as e:
            self.logger.error(f"Fehler während der Überwachung: {e}")
        finally:
            self.running = False
            self.logger.info("Überwachung beendet")
            
        return True
    
    def stop(self):
        """Stoppt die Überwachung."""
        self.running = False
        self.logger.info("Überwachung wird gestoppt...")
