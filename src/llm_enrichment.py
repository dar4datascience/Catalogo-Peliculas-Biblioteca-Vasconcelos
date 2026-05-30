"""
LLM-assisted movie enrichment module.
Uses intelligent title analysis to improve OMDB match rates.
"""

import json
import os
import re
from typing import Optional

import requests
from dotenv import load_dotenv

from omdb_client import search_movie_bilingual, get_movie_details, find_best_fuzzy_match, broad_search_movie
from models import Movie

load_dotenv()

# LLM API configuration (supports OpenAI, Anthropic, or custom)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # openai, anthropic, custom
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")

# Title cleaning patterns for PDF extraction artifacts
EXTRACTION_ARTIFACTS = [
    r'\d+\s*=\s*',  # Numbers followed by equals
    r'=+\s*$',  # Trailing equals
    r'\s+\d+\s*$',  # Trailing numbers
    r'^[\s\d\.]+',  # Leading numbers/spaces
    r'\(continua\)',  # Continuation markers
    r'\(cont\.?\)',
    r'\.{3,}',  # Excessive dots
]


class TitleAnalyzer:
    """Analyzes and normalizes movie titles using pattern matching and optional LLM."""
    
    # Common Spanish-English title mappings (well-known films)
    KNOWN_TRANSLATIONS = {
        'el padrino': 'the godfather',
        'la lista de schindler': "schindler's list",
        'titanic': 'titanic',
        'el senor de los anillos': 'the lord of the rings',
        'harry potter': 'harry potter',
        'star wars': 'star wars',
        'la guerra de las galaxias': 'star wars',
        'el mago de oz': 'the wizard of oz',
        'lo que el viento se llevo': 'gone with the wind',
        'casablanca': 'casablanca',
        'ciudadano kane': 'citizen kane',
        'psicosis': 'psycho',
        'el resplandor': 'the shining',
        'tiburon': 'jaws',
        'los pajaros': 'the birds',
        'vertigo': 'vertigo',
        'ventana indiscreta': 'rear window',
        'con la muerte en los talones': 'north by northwest',
        'la ventana indiscreta': 'rear window',
        'perdicion': 'double indemnity',
        'el gran dictador': 'the great dictator',
        'aurora': 'sunrise',
        'el acorazado potemkin': 'battleship potemkin',
        'metropolis': 'metropolis',
        'nace una estrella': 'a star is born',
        'lo haras': 'you will',
        'hagamoslo': "let's do it",
        'cantando bajo la lluvia': 'singin\' in the rain',
        'un americano en paris': 'an american in paris',
        'gigi': 'gigi',
        'my fair lady': 'my fair lady',
        'el sonido de la musica': 'the sound of music',
        'mary poppins': 'mary poppins',
        'el jorobado de notre dame': 'the hunchback of notre dame',
        'la bella y la bestia': 'beauty and the beast',
        'los fantasticos': 'the fantastic four',
    }
    
    # Genre patterns that help identify documentaries
    DOCUMENTARY_INDICATORS = [
        'documental', 'documentary', 'biografia', 'biopic',
        'historia de', 'vida de', 'la verdadera historia',
        'el mundo de', 'secretos de', 'misterios de'
    ]
    
    @staticmethod
    def clean_extraction_artifacts(title: str) -> str:
        """Remove PDF extraction artifacts from title."""
        cleaned = title
        for pattern in EXTRACTION_ARTIFACTS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip(' ,.=:-')
    
    @staticmethod
    def detect_language(title: str) -> str:
        """Detect if title is Spanish or English."""
        spanish_indicators = ['el ', 'la ', 'los ', 'las ', 'un ', 'una ', 'y ', 'de ', 'en ']
        english_indicators = ['the ', 'a ', 'an ', 'and ', 'of ', 'in ', 'to ']
        
        title_lower = title.lower()
        spanish_score = sum(1 for ind in spanish_indicators if ind in title_lower)
        english_score = sum(1 for ind in english_indicators if ind in title_lower)
        
        if spanish_score > english_score:
            return 'spanish'
        elif english_score > spanish_score:
            return 'english'
        return 'unknown'
    
    @classmethod
    def normalize_title(cls, title: str, category: str = "") -> dict:
        """
        Normalize a title for better OMDB matching.
        Returns normalized versions and metadata.
        """
        original = title
        
        # Step 1: Clean extraction artifacts
        cleaned = cls.clean_extraction_artifacts(title)
        
        # Step 2: Fix swapped articles
        if ',' in cleaned:
            parts = [p.strip() for p in cleaned.split(',')]
            if len(parts) == 2:
                article = parts[1].lower()
                if article in ['el', 'la', 'los', 'las', 'the', 'a', 'an']:
                    cleaned = f"{parts[1]} {parts[0]}"
        
        # Step 3: Detect language
        language = cls.detect_language(cleaned)
        
        # Step 4: Check known translations
        cleaned_lower = cleaned.lower()
        english_version = None
        if cleaned_lower in cls.KNOWN_TRANSLATIONS:
            english_version = cls.KNOWN_TRANSLATIONS[cleaned_lower]
        
        # Step 5: Detect if documentary based on title + category
        is_documentary = (
            'documental' in category.lower() or
            any(ind in cleaned_lower for ind in cls.DOCUMENTARY_INDICATORS)
        )
        
        # Step 6: Handle special cases
        variations = [cleaned]
        
        # Add version without accents for better matching
        import unicodedata
        no_accents = ''.join(
            c for c in unicodedata.normalize('NFD', cleaned)
            if unicodedata.category(c) != 'Mn'
        )
        if no_accents != cleaned:
            variations.append(no_accents)
        
        # Add English version if Spanish detected
        if language == 'spanish' and not english_version:
            # Generate likely English title
            english_guess = cls._guess_english_title(cleaned)
            if english_guess:
                variations.append(english_guess)
        
        return {
            'original': original,
            'cleaned': cleaned,
            'language': language,
            'variations': list(set(variations)),
            'likely_english': english_version,
            'is_documentary': is_documentary,
            'suggested_search_order': cls._build_search_order(cleaned, english_version, language)
        }
    
    @staticmethod
    def _guess_english_title(spanish_title: str) -> Optional[str]:
        """Attempt to guess English title from Spanish (basic heuristic)."""
        title_lower = spanish_title.lower()
        
        # Article swap mappings
        article_swaps = {
            r'^el\s+': 'the ',
            r'^la\s+': 'the ',
            r'^los\s+': 'the ',
            r'^las\s+': 'the ',
            r'^un\s+': 'a ',
            r'^una\s+': 'a ',
        }
        
        english = spanish_title
        for pattern, replacement in article_swaps.items():
            english = re.sub(pattern, replacement, english, flags=re.IGNORECASE)
        
        # Only return if changed
        if english.lower() != spanish_title.lower():
            return english
        return None
    
    @staticmethod
    def _build_search_order(cleaned: str, english: Optional[str], language: str) -> list:
        """Build prioritized list of search terms."""
        order = [cleaned]
        
        if language == 'spanish':
            # Spanish: try original, then English guess, then fuzzy
            if english:
                order.append(english)
        else:
            # English: try variations without articles
            no_article = re.sub(r'^(the|a|an)\s+', '', cleaned, flags=re.IGNORECASE)
            if no_article != cleaned:
                order.append(no_article)
        
        return order


def llm_enrich_movie(
    movie: Movie,
    use_llm_api: bool = False,
    director_hint: str = "",
    year_hint: str = ""
) -> dict:
    """
    Enrich a movie using intelligent title analysis + optional LLM.
    
    Args:
        movie: Movie object to enrich
        use_llm_api: Whether to call external LLM API (requires API key)
        director_hint: Optional director from PDF context
        year_hint: Optional year from PDF context
    
    Returns:
        Enrichment result dict with 'enriched' boolean and movie data
    """
    # Step 1: Analyze and normalize title
    analysis = TitleAnalyzer.normalize_title(
        movie.title,
        category=movie.pdf_category
    )
    
    # Step 2: Try search variations in order
    search_terms = analysis['suggested_search_order']
    
    if analysis.get('likely_english'):
        search_terms.insert(1, analysis['likely_english'])
    
    # Try each search term
    for term in search_terms:
        match = search_movie_bilingual(term)
        
        if match:
            # Get full details
            details = get_movie_details(match['imdbID'])
            if details:
                # Verify director if hint provided
                if director_hint and details.get('Director'):
                    if director_hint.lower() not in details['Director'].lower():
                        # Director mismatch - continue searching
                        continue
                
                return {
                    'enriched': True,
                    'data': details,
                    'match_type': match.get('match_type', 'llm_optimized'),
                    'searched_title': term,
                    'original_title': movie.title,
                    'normalization_analysis': analysis
                }
    
    # Step 3: Try fuzzy matching as last resort via broad search
    broad_results = broad_search_movie(movie.title)
    
    if broad_results:
        # Try fuzzy matching on broad results
        best_match = find_best_fuzzy_match(movie.title, broad_results)
        
        if best_match and best_match.get('score', 0) > 60:
            # Try to get details for the best match
            details = get_movie_details(best_match['imdbID'])
            if details:
                return {
                    'enriched': True,
                    'data': details,
                    'match_type': f"fuzzy_{best_match.get('score', 0)}",
                    'searched_title': best_match.get('title', movie.title),
                    'confidence': best_match.get('score', 0),
                    'original_title': movie.title,
                    'normalization_analysis': analysis
                }
    
    # Failed to enrich
    return {
        'enriched': False,
        'original_title': movie.title,
        'normalization_analysis': analysis,
        'attempted_searches': search_terms
    }


def batch_llm_enrich(
    movies: list[Movie],
    progress_callback=None
) -> list[tuple[Movie, dict]]:
    """
    Batch process movies with LLM-assisted enrichment.
    
    Args:
        movies: List of Movie objects
        progress_callback: Optional callback(count, total) for progress
    
    Returns:
        List of (Movie, result) tuples
    """
    results = []
    
    for i, movie in enumerate(movies):
        result = llm_enrich_movie(movie)
        results.append((movie, result))
        
        if progress_callback:
            progress_callback(i + 1, len(movies))
    
    return results


def generate_llm_prompt_for_failed(title: str, analysis: dict, context: str = "") -> str:
    """
    Generate a prompt for external LLM to identify a problematic title.
    Can be used when automatic matching fails.
    """
    return f"""I need to identify this movie from a library PDF catalog:

RAW EXTRACTED TITLE: "{title}"
LANGUAGE DETECTED: {analysis.get('language', 'unknown')}
VARIATIONS TRIED: {', '.join(analysis.get('variations', []))}
IS DOCUMENTARY: {analysis.get('is_documentary', False)}
{context and f'ADDITIONAL CONTEXT: {context}' or ''}

This title failed automatic OMDB matching. Please:
1. Identify what the actual movie title likely is
2. Provide both Spanish and English titles if applicable
3. Suggest the correct OMDB search strategy
4. If multiple possibilities exist, list them ranked by likelihood

Format your response as JSON:
{{
    "identified_title": "The most likely correct title",
    "alternative_titles": ["other", "possibilities"],
    "imdb_id_if_known": "tt0000000 or null",
    "confidence": "high|medium|low",
    "reasoning": "Brief explanation of your analysis"
}}"""


# Convenience function for the pipeline
def enhanced_enrich_movie(movie: Movie) -> Movie:
    """
    Enhanced enrichment wrapper for use in pipeline.
    Applies LLM-assisted analysis before standard enrichment.
    """
    result = llm_enrich_movie(movie)
    
    if result.get('enriched'):
        movie.enriched = True
        movie.match_type = result.get('match_type', 'llm_enhanced')
        movie.searched_title = result.get('searched_title')
        movie.matched_title = result.get('data', {}).get('Title')
        
        # Map all OMDB fields
        data = result.get('data', {})
        movie.imdb_id = data.get('imdbID')
        movie.year = data.get('Year')
        movie.director = data.get('Director')
        movie.writer = data.get('Writer')
        movie.actors = data.get('Actors')
        movie.plot = data.get('Plot')
        movie.language = data.get('Language')
        movie.country = data.get('Country')
        movie.awards = data.get('Awards')
        movie.poster = data.get('Poster') if data.get('Poster') != 'N/A' else None
        movie.imdb_rating = data.get('imdbRating')
        movie.imdb_votes = data.get('imdbVotes')
        movie.metascore = data.get('Metascore')
        
        # Parse genre
        genre_str = data.get('Genre', '')
        if genre_str:
            movie.genre = [g.strip() for g in genre_str.split(',')]
    
    return movie
