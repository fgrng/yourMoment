import os
import time

from mistralai import Mistral
#from mistralai.client import MistralClient
#from mistralai.models.chat_completion import ChatMessage

from .base import BaseCommenter

class MistralAICommenter(BaseCommenter):
    """Klasse zur Generierung von KI-Kommentaren für myMoment-Beiträge mittels Mistral AI."""

    ## Grundlage für Systemprompt
    system_prompt_base = """# Kontext

Du bist ein 10-jähriger Schüler oder eine 10-jährige Schülerin aus der 4. Klasse einer Schweizer Primarschule. 
Du benutzt eine digitale Schreibplattform, wo deine Klasse Texte schreibt und gegenseitig kommentiert.

# Sprache

Deine Muttersprache ist Schweizerdeutsch (Dialekt), aber auf der Plattform schreibst du in Standarddeutsch mit typisch schweizerischen Ausdrücken und gelegentlichen Einflüssen aus dem Schweizerdeutschen.

## Sprachgebrauch

Wortschatz: Verwende einen altersgerechten, einfachen Wortschatz eines 10-Jährigen.
Satzstruktur: Deine Sätze sind meist kurz und einfach strukturiert, manchmal mit grammatikalischen Fehlern.
Typische Ausdrücke: Verwende schweizertypische Ausdrücke wie "mega cool", "voll lässig", "gfalle mir", "isch schön gsi", "das find ich geil".
Helvetismen: Nutze schweizertypische Wörter wie "Znüni" (Pausenbrot), "Finken" (Hausschuhe), "Velo" (Fahrrad), "Trottinett" (Roller).
Begrüssungen: "Hoi", "Sali", "Tschau", "Hallo zäme"

## Schreibstil für Kommentare

Antworte nur mit einem kurzen Kommentar von 1–3 Sätzen.
Beziehe dich auf konkrete Teile des Textes.
Du bist grundsätzlich freundlich und unterstützend.
Du sagst offen, was dir gefällt oder was du nicht verstanden hast.
Verwende ab und zu einfache Emoticons.

## Beispielformulierungen für Kommentare

"Hoi! Din Text isch mega cool. Mir gfallt bsunders, wie du..."
"Sali! Das isch e tolle Gschicht. Ich finde guet, dass..."
"Ich finds cool, wie du das beschrieben hast. Ich han au scho mal..."
"Ich han nöd ganz verstande, wieso... Chasch mir das erkläre?"
"Das erinneret mich a min Cousin, wo au gern..."
"Wow, mega spannend, was du gschribe hesch!..."
"Ich finds cool, wie du das geschrieben hast. Was passiert nacher no?..."
"Haha, das hani lustig gfunde!..."

## Was zu vermeiden ist

Komplexe Satzstrukturen mit vielen Nebensätzen;
Fachbegriffe oder Fremdwörter, die ein 10-Jähriger nicht kennen würde;
Zu tiefgründige oder philosophische Betrachtunge;
Zu formelle oder erwachsene Ausdrucksweise;
Perfekte Rechtschreibung und Grammatik"""

    user_prompt_base = """# Instruktion

{instruction}

Du schreibst einen Kommentar für diesen Beitrag:

<titel>
{{student_title}}
</titel>
<autor>
{{student_author}}
</autor>   
<beitrag>
{{student_text}}
</beitrag>"""
    
    def __init__(self, api_key=None, model="mistral-small-latest", style="motivation", styles={}, temperature=0.7, **kwargs):
        """
        Initialisiert den MistralAI-Kommentierer.
        
        Args:
            api_key (str, optional): Mistral API-Schlüssel. Falls nicht angegeben, wird nach der MISTRAL_API_KEY-Umgebungsvariable gesucht.
            model (str, optional): Zu verwendendes Mistral-Modell. Standard ist "mistral-large-latest".
            styles (dict, optional): Wörterbuch mit benutzerdefinierten Kommentarstilen.
            default_style (str, optional): Standard-Kommentarstil. Standard ist "helpful".
            **kwargs: Weitere Konfigurationsparameter.
        """
        super().__init__(**kwargs)
        
        ## API-Schlüssel aus Umgebungsvariable holen, falls nicht angegeben
        self.api_key = api_key or os.environ.get("MISTRAL_API_KEY")
        if not self.api_key:
            raise ValueError("Mistral API-Schlüssel nicht angegeben und MISTRAL_API_KEY-Umgebungsvariable nicht gesetzt")
        
        self.model = model
        self.temperature = temperature
        self.style = style
        self.client = Mistral(api_key=self.api_key)
             
        ## Vordefinierte Kommentarstile / Systemprompts
        self.styles = {
            ## Einfache Prompts
            "motivation": "Du kommentierst einen Beitrag auf der digitalen Schreibplattform. Gib Lob und ermuntere das Kind, noch mehr zu schreiben oder weiter nachzudenken. Sage auch, was Dir ganz besonders gefallen hat.",
            "questioning": "Du kommentierst einen Beitrag auf der digitalen Schreibplattform. Stelle kritische, aber höfliche Fragen zum Text, um den Autor zum Nachdenken anzuregen.",
            ## Systemprompts für Schreibarrangements
            "arrangement_10": """Du kommentierst einen Kommentar auf der digitalen Schreibplattform zu einem Beitrag für eine spezielle Schreibaufgabe.

## Schreibaufgabe

Thema: Zwei Gegenstände treffen sich an einem für sie ungewöhnlichen Ort. Sie wissen aber nicht, wo sie sind und wie sie da hingekommen sind.
Textsorte: erfundener Dialog zwischen den beiden Gegenständen
Schreibziel: Der Dialog ist so geschrieben, dass die Leserinnen und Leser herausfinden müssen, welche Gegenstände miteinander reden.

## Kommentar

Versuche die beiden Gegenstände und den Ort zu erraten."""
        }
        
        ## Benutzerdefinierte Stile hinzufügen oder überschreiben, falls angegeben
        if styles:
            self.styles.update(styles)

        ## Systemprompt vorbereiten
        self.system_prompt = MistralAICommenter.system_prompt_base

        ## Userprompt vorbereiten
        self.user_prompt = MistralAICommenter.user_prompt_base.format(instruction = self.styles[self.style])
        
    def generate_comment(self, post, max_tokens=300, highlight=None, **kwargs):
        """
        Generiert einen Kommentar für einen Beitrag basierend auf dem angegebenen Stil.
        
        Args:
            post (dict): Das Post-Dictionary mit den Beitragsdetails.
            style (str, optional): Der Stil des zu generierenden Kommentars. Falls nicht angegeben, wird der Standardstil verwendet.
            max_tokens (int, optional): Maximale Länge des generierten Kommentars.
            highlight (str, optional): Hervorgehobener Text, falls vorhanden.
            **kwargs: Zusätzliche Parameter.
            
        Returns:
            str: Der generierte Kommentar.
        """
        
        ## Relevante Inhalte aus dem Beitrag extrahieren
        student_title = post.get('title', 'Unbekannter Titel')
        student_text = post.get('full_html', '')
        student_author = post.get('author', 'Unbekannter Autor')
        
        ## Inhalt bereinigen, falls erforderlich
        # if not student_text and post.get('full_html'):
        #     from bs4 import BeautifulSoup
        #     soup = BeautifulSoup(post['full_html'], 'html.parser')
        #     student_text = soup.get_text(separator=' ', strip=True)
        
        ## Prompt vorbereiten
        specific_user_prompt = self.user_prompt.format(student_title = student_title, student_author = student_author, student_text = student_text)
        
        try:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": specific_user_prompt}
            ]
            
            ## Mistral API aufrufen
            response = self.client.chat.complete(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=self.temperature  ## Etwas Zufälligkeit für menschlichere Antworten hinzufügen
            )
            
            ## Antwort extrahieren und bereinigen
            comment = response.choices[0].message.content.strip()
            
            ## Quote-Formatierung entfernen, falls vorhanden
            # comment = comment.replace('```', '').strip()
            
            # ## Standardphrasen wie "Hier ist mein Kommentar:" entfernen, falls vorhanden
            # phrases_to_remove = [
            #     "Hier ist mein Kommentar:",
            #     "Mein Kommentar:",
            #     "Mein Kommentar dazu:",
            #     "Hier ist ein Kommentar:"
            # ]
            
            # for phrase in phrases_to_remove:
            #     if comment.startswith(phrase):
            #         comment = comment[len(phrase):].strip()
            
            return comment
            
        except Exception as e:
            print(f"Fehler bei der Kommentargenerierung: {e}")
            # if highlight:
            #     return f"Diese Stelle im Text finde ich besonders interessant. Kannst du dazu noch mehr erzählen?"
            # else:
            #     return f"Interessanter Beitrag! Ich habe dazu einige Gedanken, die ich später teilen werde."
    
    def generate_highlight_comment(self, post, highlight_text, style=None, max_tokens=300, **kwargs):
        """
        Generiert einen Kommentar für einen hervorgehobenen Text in einem Beitrag.
        
        Args:
            post (dict): Das Post-Dictionary mit den Beitragsdetails.
            highlight_text (str): Der hervorgehobene Text, der kommentiert werden soll.
            style (str, optional): Der Stil des zu generierenden Kommentars.
            max_tokens (int, optional): Maximale Länge des generierten Kommentars.
            **kwargs: Zusätzliche Parameter.
            
        Returns:
            str: Der generierte Kommentar zum hervorgehobenen Text.
        """
        ## Standardmäßig den "questioning"-Stil für Hervorhebungen verwenden
        if style is None:
            style = "questioning"
            
        return self.generate_comment(
            post, 
            style=style, 
            max_tokens=max_tokens, 
            highlight=highlight_text,
            **kwargs
        )
