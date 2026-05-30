import os
import re
from typing import Optional

import requests
from dotenv import load_dotenv
from thefuzz import fuzz

load_dotenv()

API_KEY = os.getenv("OMDB_API_KEY")
BASE_URL = "http://www.omdbapi.com/"

# Common Spanish article mappings for title normalization
SPANISH_ARTICLES = {
    'el ', 'la ', 'los ', 'las ', 'un ', 'una ', 'unos ', 'unas ',
    'al ', 'del '
}

# Title pattern mappings (Spanish -> English equivalents for fallback)
TITLE_PATTERNS = {
    r'^el\s+': 'the ',
    r'^la\s+': 'the ',
    r'^los\s+': 'the ',
    r'^las\s+': 'the ',
    r'^un\s+': 'a ',
    r'^una\s+': 'a ',
}


def normalize_spanish_title(title: str) -> str:
    """Normalize Spanish title for better matching."""
    title = title.lower().strip()
    # Handle swapped articles: "Pelicula, La" -> "La Pelicula"
    if ',' in title:
        parts = [p.strip() for p in title.split(',')]
        if len(parts) == 2 and parts[1] in ['el', 'la', 'los', 'las', 'the']:
            title = f"{parts[1]} {parts[0]}"
    return title.strip()


def spanish_to_english_title(title: str) -> str:
    """Convert Spanish title patterns to English for fallback search."""
    title = normalize_spanish_title(title)
    for pattern, replacement in TITLE_PATTERNS.items():
        if re.match(pattern, title):
            return re.sub(pattern, replacement, title, count=1)
    return title

def _query_omdb(params):
    """Helper function to query the OMDb API and handle responses."""
    try:
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if data.get('Response') == 'True':
            return data
    except requests.exceptions.RequestException as e:
        print(f"Error querying OMDb: {e}")
    return None

def search_movie_id(title: str, year: Optional[str] = None) -> Optional[str]:
    """
    Searches for a movie's ID using a multi-step exact match process.
    """
    # 1. Direct search with optional year
    params = {'t': title, 'apikey': API_KEY}
    if year:
        params['y'] = year
    data = _query_omdb(params)
    if data:
        return data.get('imdbID')

    # 2. Clean trailing digits and retry
    cleaned_title = re.sub(r'\s+\d+$', '', title).strip()
    if cleaned_title != title:
        params = {'t': cleaned_title, 'apikey': API_KEY}
        if year:
            params['y'] = year
        data = _query_omdb(params)
        if data:
            return data.get('imdbID')

    # 3. Handle swapped titles (e.g., "Title, The") and retry
    if ',' in cleaned_title:
        parts = [part.strip() for part in cleaned_title.split(',')]
        if len(parts) == 2:
            swapped_title = f"{parts[1]} {parts[0]}"
            params = {'t': swapped_title, 'apikey': API_KEY}
            if year:
                params['y'] = year
            data = _query_omdb(params)
            if data:
                return data.get('imdbID')
    return None


def search_movie_bilingual(title: str, year: Optional[str] = None, preferred_language: str = 'es') -> Optional[dict]:
    """
    Search for a movie using bilingual strategy (Spanish -> English fallback).

    Args:
        title: Movie title (can be in Spanish)
        year: Optional release year
        preferred_language: Preferred language ('es' or 'en')

    Returns:
        dict with 'imdbID' and match metadata, or None if not found.
    """
    normalized = normalize_spanish_title(title)

    # 1. Try exact match with original/normalized title
    movie_id = search_movie_id(normalized, year)
    if movie_id:
        return {'imdbID': movie_id, 'match_type': 'exact_spanish', 'searched_title': normalized}

    # 2. Try with Spanish articles handled
    cleaned = normalized
    for article in SPANISH_ARTICLES:
        if cleaned.startswith(article):
            cleaned = cleaned[len(article):].strip()
            movie_id = search_movie_id(cleaned, year)
            if movie_id:
                return {'imdbID': movie_id, 'match_type': 'no_article', 'searched_title': cleaned}
            break

    # 3. Try broad search and fuzzy match
    matches = broad_search_movie(normalized)
    if matches:
        best_match = find_best_fuzzy_match(normalized, matches)
        if best_match and best_match['score'] > 70:
            return {
                'imdbID': best_match['imdbID'],
                'match_type': f"fuzzy_{best_match['score']}",
                'searched_title': normalized,
                'matched_title': best_match['title']
            }

    # 4. English fallback for Spanish titles
    english_title = spanish_to_english_title(title)
    if english_title != normalized:
        movie_id = search_movie_id(english_title, year)
        if movie_id:
            return {'imdbID': movie_id, 'match_type': 'english_fallback', 'searched_title': english_title}

    return None


def find_best_fuzzy_match(query: str, candidates: list) -> Optional[dict]:
    """
    Find the best fuzzy match from a list of OMDB search results.

    Args:
        query: Original search query
        candidates: List of OMDB search result dicts with 'Title' and 'imdbID'

    Returns:
        Best matching candidate with 'score', 'imdbID', 'title', or None.
    """
    if not candidates:
        return None

    best_score = 0
    best_match = None

    query = query.lower().strip()

    for candidate in candidates:
        candidate_title = candidate.get('Title', '').lower().strip()

        # Use weighted fuzzy ratio
        score = fuzz.ratio(query, candidate_title)
        token_score = fuzz.token_sort_ratio(query, candidate_title)

        # Combine scores, favoring exact ratio but considering token order
        final_score = max(score, token_score)

        if final_score > best_score:
            best_score = final_score
            best_match = {
                'imdbID': candidate.get('imdbID'),
                'title': candidate.get('Title'),
                'score': final_score
            }

    return best_match if best_score > 50 else None

def broad_search_movie(title: str, year: Optional[str] = None) -> Optional[list]:
    """Performs a broad search and returns all potential matches."""
    cleaned_title = normalize_spanish_title(title)
    cleaned_title = re.sub(r'\s+\d+$', '', cleaned_title).strip()

    params = {'s': cleaned_title, 'apikey': API_KEY}
    if year:
        params['y'] = year

    search_data = _query_omdb(params)
    if search_data and 'Search' in search_data:
        return search_data['Search']
    return None

def get_movie_details(imdb_id: str, include_full_plot: bool = True) -> Optional[dict]:
    """
    Fetches movie details using its Movie ID.

    Args:
        imdb_id: The Movie ID of the movie.
        include_full_plot: Whether to fetch full plot (True) or short plot (False).

    Returns:
        A dictionary containing the movie's details, or None if not found.
    """
    params = {
        'i': imdb_id,
        'plot': 'full' if include_full_plot else 'short',
        'apikey': API_KEY
    }
    try:
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if data.get('Response') == 'True':
            return data
        else:
            print(f"Could not fetch details for Movie ID '{imdb_id}': {data.get('Error')}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching details for Movie ID '{imdb_id}': {e}")
        return None


def enrich_movie_with_omdb(title: str, source_pdf: str = '', year: Optional[str] = None) -> dict:
    """
    Full enrichment pipeline for a single movie title.

    Args:
        title: Movie title (Spanish or English)
        source_pdf: Source PDF filename for tracking
        year: Optional release year hint

    Returns:
        dict with movie details, match metadata, and source info.
    """
    result = {
        'original_title': title,
        'source_pdf': source_pdf,
        'enriched': False,
        'match_type': None,
        'data': None
    }

    # Try bilingual search
    match = search_movie_bilingual(title, year, preferred_language='es')

    if match:
        details = get_movie_details(match['imdbID'])
        if details:
            result['enriched'] = True
            result['match_type'] = match.get('match_type', 'unknown')
            result['searched_title'] = match.get('searched_title', title)
            result['matched_title'] = match.get('matched_title', details.get('Title'))
            result['data'] = details
            # Add computed fields
            result['director'] = details.get('Director', '')
            result['year'] = details.get('Year', '')
            result['genre'] = details.get('Genre', '').split(', ') if details.get('Genre') else []
            result['country'] = details.get('Country', '')
            result['plot'] = details.get('Plot', '')
            result['poster'] = details.get('Poster', '')
            result['imdb_rating'] = details.get('imdbRating', '')

    return result
