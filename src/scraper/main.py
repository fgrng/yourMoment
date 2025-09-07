from .auth import SessionManager
from .posts import PostManager
from .comments import CommentManager
from .monitor import PostMonitor

class WebScraper:
    """Hauptklasse für den myMoment Web Scraper.
    
    Diese Klasse dient als Fassade (Facade Pattern) für die verschiedenen Manager-Klassen
    und bietet eine einheitliche Schnittstelle für die Anwendung.
    """
    
    def __init__(self, base_url="https://new.mymoment.ch"):
        self.base_url = base_url
        self.session_manager = SessionManager(base_url)
        self.post_manager = PostManager(self.session_manager)
        self.comment_manager = CommentManager(self.session_manager, self.post_manager)
        self.monitor = None  # Wird bei Bedarf initialisiert
        
    ## Session-Management-Methoden
    def is_logged_in(self):
        return self.session_manager.is_logged_in()
        
    def login(self, username, password):
        return self.session_manager.login(username, password)
        
    def save_session(self):
        self.session_manager.save_session()
        
    ## Post-Management-Methoden
    def get_posts(self, limit=10, tab="home"):
        return self.post_manager.get_posts(limit, tab)
        
    def get_post(self, post_id):
        return self.post_manager.get_post(post_id)
    
    def create_post(self, title, content, category_id=None):
        return self.post_manager.create_post(title, content, category_id)
        
    def update_post(self, post_id, title=None, content=None, category_id=None, status_id=None):
        return self.post_manager.update_post(post_id, title, content, category_id, status_id)
        
    def publish_post(self, post_id):
        return self.post_manager.publish_post(post_id)
        
    def draft_post(self, post_id):
        return self.post_manager.draft_post(post_id)
        
    def like_post(self, post_id):
        return self.post_manager.like_post(post_id)
        
    def get_categories(self):
        return self.post_manager.get_categories()
    
    ## Kommentar-Management-Methoden
    def get_comments(self, post_id):
        return self.comment_manager.get_comments(post_id)
        
    def add_comment(self, post_id, text, highlight=None, hidden=False):
        return self.comment_manager.add_comment(post_id, text, highlight, hidden)
        
    def edit_comment(self, comment_id, text):
        return self.comment_manager.edit_comment(comment_id, text)

    ## Monitoring-Methoden
    def get_monitor(self):
        """Gibt eine Monitor-Instanz zurück oder erstellt sie, falls noch nicht vorhanden."""
        if self.monitor is None:
            self.monitor = PostMonitor(self)
        return self.monitor
        
    def start_monitoring(self, interval=300, tab="alle", category=0, commenter=None, max_posts=20, max_runtime=None, dry_run=False, hidden=False):
        """Startet die Überwachung nach neuen Beiträgen."""
        monitor = self.get_monitor()
        return monitor.monitor(interval, tab, category, commenter, max_posts, max_runtime, dry_run, hidden)
        
    def stop_monitoring(self):
        """Stoppt die laufende Überwachung."""
        if self.monitor:
            self.monitor.stop()
            return True
        return False
