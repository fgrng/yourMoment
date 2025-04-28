"""
Template-basierter Kommentierer für myMoment-Webscraper.
Verwendet vordefinierte Vorlagen zur Generierung von Kommentaren.
"""

import random
import re
from .base import BaseCommenter

class TemplateCommenter(BaseCommenter):
    """Klasse zur Generierung von Kommentaren auf Basis vordefinierter Vorlagen."""
    
    def __init__(self, templates=None, highlight_templates=None, **kwargs):
        """
        Initialisiert den Template-Kommentierer.
        
        Args:
            templates (list, optional): Liste mit Kommentarvorlagen.
            highlight_templates (list, optional): Liste mit Kommentarvorlagen für Hervorhebungen.
            **kwargs: Weitere Konfigurationsparameter.
        """
        super().__init__(**kwargs)
        
        ## Standard-Kommentarvorlagen, falls keine angegeben wurden
        self.templates = templates or [
            "Sehr interessanter Beitrag! Besonders {keyword} hat mich zum Nachdenken angeregt.",
            "Danke für diesen Beitrag. Der Teil über {keyword} fand ich besonders gelungen.",
            "Das ist ein guter Punkt zum Thema {keyword}. Hast du darüber noch weitere Gedanken?",
            "Ich finde deine Perspektive zu {keyword} sehr aufschlussreich.",
            "Deine Ausführungen zu {keyword} haben mir neue Einsichten gegeben.",
            "Ein wirklich gut durchdachter Beitrag! Die Verbindung zu {keyword} ist sehr interessant.",
            "Spannende Ideen! Besonders der Aspekt über {keyword} ist bemerkenswert."
        ]
        
        ## Vorlagen für Hervorhebungen
        self.highlight_templates = highlight_templates or [
            "Diese Passage finde ich besonders interessant. Kannst du mehr über {highlight} erzählen?",
            "Bei \"{highlight}\" musste ich innehalten. Was genau meinst du damit?",
            "Der Teil \"{highlight}\" hat mich neugierig gemacht. Hast du dazu weitere Gedanken?",
            "Warum hast du genau \"{highlight}\" so formuliert? Das finde ich spannend.",
            "Dieser Punkt ist wichtig: \"{highlight}\". Könntest du das noch vertiefen?",
            "Die Formulierung \"{highlight}\" gefällt mir besonders. Ist das eine bewusste Wahl?"
        ]
        
        ## Schlüsselwörter für allgemeine Kategorien
        self.fallback_keywords = [
            "deine Argumentation", "deine Ideen", "deine Darstellung", 
            "dieser Aspekt", "deine Analyse", "deine Erklärung",
            "deine Überlegungen", "deine Herangehensweise", "deine Sichtweise"
        ]
    
    def _extract_keywords(self, text, count=3):
        """
        Extrahiert potenzielle Schlüsselwörter aus dem Text.
        
        Args:
            text (str): Quelltext, aus dem Schlüsselwörter extrahiert werden sollen.
            count (int): Anzahl der zu extrahierenden Schlüsselwörter.
            
        Returns:
            list: Liste mit extrahierten Schlüsselwörtern.
        """
        if not text:
            return self.fallback_keywords
            
        ## Einfache Heuristik: Substantive sind oft länger und nicht in Stoppwörtern enthalten
        words = re.findall(r'\b[A-Za-zäöüÄÖÜß]{4,}\b', text)
        stopwords = {"und", "oder", "aber", "denn", "weil", "dass", "wenn", "dann", "also", "jedoch", "trotzdem"}
        
        filtered_words = [word for word in words if word.lower() not in stopwords]
        
        ## Wenn nicht genug Wörter gefunden wurden, Fallback verwenden
        if len(filtered_words) < count:
            return self.fallback_keywords
            
        ## Die häufigsten Wörter auswählen
        word_freq = {}
        for word in filtered_words:
            word_freq[word] = word_freq.get(word, 0) + 1
            
        sorted_words = sorted(word_freq.items(), key=lambda item: item[1], reverse=True)
        return [word for word, _ in sorted_words[:count]]
    
    def generate_comment(self, post, highlight=None, **kwargs):
        """
        Generiert einen Kommentar für einen Beitrag basierend auf vordefinierten Vorlagen.
        
        Args:
            post (dict): Das Post-Dictionary mit den Beitragsdetails.
            highlight (str, optional): Hervorgehobener Text, falls vorhanden.
            **kwargs: Zusätzliche Parameter.
            
        Returns:
            str: Der generierte Kommentar.
        """
        if highlight:
            return self.generate_highlight_comment(post, highlight)
            
        title = post.get('title', 'Unbekannter Titel')
        content = post.get('content', '')
        
        ## Inhalt bereinigen, falls erforderlich
        # if not content and post.get('full_html'):
        #     from bs4 import BeautifulSoup
        #     soup = BeautifulSoup(post['full_html'], 'html.parser')
        #     content = soup.get_text(separator=' ', strip=True)
        
        ## Kombinierten Text für Schlüsselwortextraktion erstellen
        full_text = f"{title} {content}"
        
        ## Schlüsselwörter extrahieren
        keywords = self._extract_keywords(full_text)
        
        ## Zufällige Vorlage und Schlüsselwort auswählen
        template = random.choice(self.templates)
        keyword = random.choice(keywords)

        ## TODO Das Verfahren ist Quatsch :). Nutze Fallback.
        keyword = random.choice(self.fallback_keywords)
        
        ## Kommentar erstellen
        comment = template.format(keyword=keyword)
        
        return comment
    
    def generate_highlight_comment(self, post, highlight_text, **kwargs):
        """
        Generiert einen Kommentar für einen hervorgehobenen Text in einem Beitrag.
        
        Args:
            post (dict): Das Post-Dictionary mit den Beitragsdetails.
            highlight_text (str): Der hervorgehobene Text, der kommentiert werden soll.
            **kwargs: Zusätzliche Parameter.
            
        Returns:
            str: Der generierte Kommentar zum hervorgehobenen Text.
        """
        ## Schlüsselwörter aus dem hervorgehobenen Text extrahieren
        keywords = self._extract_keywords(highlight_text)
        keyword = random.choice(keywords)
        
        ## Zufällige Vorlage auswählen
        template = random.choice(self.highlight_templates)
        
        ## Kommentar erstellen
        comment = template.format(highlight=highlight_text, keyword=keyword)
        
        return comment
