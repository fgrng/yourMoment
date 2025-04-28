"""
Basis-Implementierung für Commenter-Klassen im myMoment-Scraper.
"""

from abc import ABC, abstractmethod

class BaseCommenter(ABC):
    """
    Abstrakte Basisklasse für Kommentar-Generatoren.
    Alle konkreten Commenter-Implementierungen sollten von dieser Klasse erben.
    """
    
    def __init__(self, **kwargs):
        """
        Initialisiert den Commenter mit den angegebenen Konfigurationsparametern.
        
        Args:
            **kwargs: Beliebige Konfigurationsparameter für den spezifischen Commenter.
        """
        self.config = kwargs
    
    @abstractmethod
    def generate_comment(self, post, **kwargs):
        """
        Generiert einen Kommentar für einen Beitrag.
        
        Args:
            post (dict): Das Post-Dictionary mit Informationen zum Beitrag.
            **kwargs: Optionale Parameter für die Kommentargenerierung.
            
        Returns:
            str: Der generierte Kommentar.
        """
        pass
    
    def generate_highlight_comment(self, post, highlight_text, **kwargs):
        """
        Generiert einen Kommentar für einen hervorgehobenen Text im Beitrag.
        
        Args:
            post (dict): Das Post-Dictionary mit Informationen zum Beitrag.
            highlight_text (str): Der hervorgehobene Text.
            **kwargs: Optionale Parameter für die Kommentargenerierung.
            
        Returns:
            str: Der generierte Kommentar zum hervorgehobenen Text.
        """
        ## Standardimplementierung ruft einfach generate_comment mit Hinweis auf Hervorhebung auf
        return self.generate_comment(
            post, 
            highlight=highlight_text,
            **kwargs
        )
