"""
TMDB API Client for movie catalog enrichment.
Provides functions to search persons (directors), fetch filmographies, and get movie details.
Uses Bearer token authentication.
"""

import os
import sys
import re
import time
from typing import Optional, Dict, Any, List
import requests
from dotenv import load_dotenv
from thefuzz import fuzz
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
    before_sleep_log
)
import logging

# Ensure src directory is in path for imports
sys.path.insert(0, os.path.dirname(__file__))

load_dotenv()

API_TOKEN = os.getenv("TMDB_API_TOKEN")
BASE_URL = "https://api.themoviedb.org/3"

# Common Spanish article mappings for title normalization
SPANISH_ARTICLES = {
    'el ', 'la ', 'los ', 'las ', 'un ', 'una ', 'unos ', 'unas ',
    'al ', 'del '
}


def _get_headers() -> dict:
    """Return headers with Bearer token authentication."""
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "accept": "application/json"
    }


# Configure logging for retry attempts
logger = logging.getLogger(__name__)


def is_rate_limit_error(exception):
    """Check if the exception is a rate limit (429) error."""
    if isinstance(exception, requests.exceptions.HTTPError):
        return exception.response.status_code == 429
    return False


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=0.1, max=8, jitter=1),
    retry=retry_if_exception_type((
        requests.exceptions.HTTPError,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout
    )),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def _query_tmdb_with_retry(endpoint: str, params: dict = None) -> Optional[dict]:
    """Internal function with retry logic for TMDB API calls."""
    if not API_TOKEN:
        print("Error: TMDB_API_TOKEN not set in environment variables")
        return None
    
    url = f"{BASE_URL}{endpoint}"
    
    # Add small preventive delay to stay under rate limit (~40 req/sec)
    time.sleep(0.025)  # 25ms = ~40 requests per second max
    
    response = requests.get(url, headers=_get_headers(), params=params or {})
    
    # Check for rate limit specifically to trigger retry
    if response.status_code == 429:
        response.raise_for_status()
    
    response.raise_for_status()
    return response.json()


def _query_tmdb(endpoint: str, params: dict = None) -> Optional[dict]:
    """Helper function to query the TMDB API with exponential backoff retry."""
    try:
        return _query_tmdb_with_retry(endpoint, params)
    except requests.exceptions.RequestException as e:
        if hasattr(e, 'response') and e.response is not None:
            if e.response.status_code == 429:
                print(f"Rate limit exceeded for {endpoint}: {e}")
            else:
                print(f"HTTP error {e.response.status_code} for {endpoint}: {e}")
        else:
            print(f"Error querying TMDB {endpoint}: {e}")
        return None


def normalize_title_for_matching(title: str) -> str:
    """Normalize title for better fuzzy matching."""
    title = title.lower().strip()
    # Remove punctuation except hyphens and apostrophes
    title = re.sub(r'[^\w\s\-\']', ' ', title)
    # Handle swapped articles: "Pelicula, La" -> "La Pelicula"
    if ',' in title:
        parts = [p.strip() for p in title.split(',')]
        if len(parts) == 2 and parts[1] in ['el', 'la', 'los', 'las', 'the']:
            title = f"{parts[1]} {parts[0]}"
    # Normalize whitespace
    title = ' '.join(title.split())
    return title.strip()


def search_person(name: str) -> Optional[dict]:
    """
    Search for a person (director/actor) by name using TMDB /search/person endpoint.
    
    Args:
        name: Person's name to search for
        
    Returns:
        First matching person dict with 'id', 'name', 'popularity', or None if not found
    """
    if not name or not name.strip():
        return None
    
    # Clean the name - remove common PDF artifacts
    cleaned_name = re.sub(r'^(Dir\.|dir\.|Escrita y Dir\.|Guión y Dir\.|prod\. y)\s*', '', name, flags=re.IGNORECASE)
    cleaned_name = re.sub(r',\s*\d{4}-?$', '', cleaned_name).strip().rstrip('.')
    cleaned_name = re.sub(r',\s*$', '', cleaned_name).strip()
    
    params = {
        "query": cleaned_name,
        "language": "es-ES"
    }
    
    data = _query_tmdb("/search/person", params)
    if data and data.get("results"):
        # Return the first (most popular) result
        return data["results"][0]
    return None


def get_person_movie_credits(person_id: int, include_crew: bool = True, include_cast: bool = False) -> List[dict]:
    """
    Get all movie credits for a person using /person/{person_id}/movie_credits.
    
    Args:
        person_id: TMDB person ID
        include_crew: Include movies where person worked as crew (director, writer, etc.)
        include_cast: Include movies where person acted
        
    Returns:
        List of movie dicts with 'id', 'title', 'original_title', 'release_date', 'job'
    """
    data = _query_tmdb(f"/person/{person_id}/movie_credits")
    if not data:
        return []
    
    movies = []
    seen_ids = set()
    
    if include_crew and data.get("crew"):
        for credit in data["crew"]:
            movie_id = credit.get("id")
            if movie_id and movie_id not in seen_ids:
                seen_ids.add(movie_id)
                movies.append({
                    "id": movie_id,
                    "title": credit.get("title", ""),
                    "original_title": credit.get("original_title", ""),
                    "release_date": credit.get("release_date", ""),
                    "job": credit.get("job", ""),
                    "department": credit.get("department", ""),
                    "popularity": credit.get("popularity", 0),
                    "vote_average": credit.get("vote_average", 0),
                    "vote_count": credit.get("vote_count", 0)
                })
    
    if include_cast and data.get("cast"):
        for credit in data["cast"]:
            movie_id = credit.get("id")
            if movie_id and movie_id not in seen_ids:
                seen_ids.add(movie_id)
                movies.append({
                    "id": movie_id,
                    "title": credit.get("title", ""),
                    "original_title": credit.get("original_title", ""),
                    "release_date": credit.get("release_date", ""),
                    "character": credit.get("character", ""),
                    "job": "Actor",
                    "department": "Acting",
                    "popularity": credit.get("popularity", 0),
                    "vote_average": credit.get("vote_average", 0),
                    "vote_count": credit.get("vote_count", 0)
                })
    
    # Sort by release date (newest first) and then by vote count
    movies.sort(key=lambda x: (x.get("release_date") or "", x.get("vote_count", 0)), reverse=True)
    return movies


def get_movie_details(movie_id: int, language: str = "es-ES") -> Optional[dict]:
    """
    Get full movie details using /movie/{movie_id}.
    
    Args:
        movie_id: TMDB movie ID
        language: Language for localized data (default: Spanish)
        
    Returns:
        Movie details dict or None if not found
    """
    params = {"language": language}
    return _query_tmdb(f"/movie/{movie_id}", params)


def calculate_title_similarity(query_title: str, candidate_title: str, candidate_original_title: str = "") -> dict:
    """
    Calculate similarity scores between query title and candidate titles.
    
    Args:
        query_title: The title from the catalog (Spanish usually)
        candidate_title: The TMDB localized title (Spanish/English)
        candidate_original_title: The TMDB original title
        
    Returns:
        Dict with similarity scores and match indicators
    """
    query_norm = normalize_title_for_matching(query_title)
    candidate_norm = normalize_title_for_matching(candidate_title)
    original_norm = normalize_title_for_matching(candidate_original_title) if candidate_original_title else ""
    
    # Calculate fuzzy scores
    score_vs_title = fuzz.ratio(query_norm, candidate_norm)
    token_score_vs_title = fuzz.token_sort_ratio(query_norm, candidate_norm)
    
    score_vs_original = 0
    token_score_vs_original = 0
    if original_norm:
        score_vs_original = fuzz.ratio(query_norm, original_norm)
        token_score_vs_original = fuzz.token_sort_ratio(query_norm, original_norm)
    
    # Best score
    best_score = max(score_vs_title, token_score_vs_title, score_vs_original, token_score_vs_original)
    
    # Exact match checks
    exact_match_title = query_norm == candidate_norm
    exact_match_original = query_norm == original_norm if original_norm else False
    
    return {
        "fuzzy_score": best_score,
        "exact_match_title": exact_match_title,
        "exact_match_original": exact_match_original,
        "score_vs_title": score_vs_title,
        "score_vs_original": score_vs_original
    }


def search_movie_by_title(title: str, year: Optional[str] = None) -> List[dict]:
    """
    Search for movies by title using /search/movie.
    
    Args:
        title: Movie title to search for
        year: Optional release year to filter results
        
    Returns:
        List of matching movie dicts
    """
    if not title or not title.strip():
        return []
    
    params = {
        "query": title,
        "language": "es-ES",
        "include_adult": "false"
    }
    if year:
        params["year"] = year
    
    data = _query_tmdb("/search/movie", params)
    if data and data.get("results"):
        return data["results"]
    return []


def find_best_match_in_filmography(
    query_title: str,
    filmography: List[dict],
    query_director: str = "",
    use_hybrid: bool = False,
) -> Optional[dict]:
    """
    Find the best matching movie in a director's filmography.

    Args:
        query_title: The title from the catalog
        filmography: List of movies from TMDB person/movie_credits
        query_director: Optional director name for verification
        use_hybrid: If True, delegate to TMDBDuckDB.find_best_match_hybrid
                    for Jaro-Winkler + BM25 + cosine scoring (requires
                    the director to already be loaded in the DuckDB store).

    Returns:
        Best matching movie with confidence score, or None
    """
    if not filmography:
        return None

    if use_hybrid and query_director:
        try:
            from tmdb_duckdb import TMDBDuckDB
            with TMDBDuckDB() as db:
                match = db.find_best_match_hybrid(query_title, query_director)
            if match:
                # Wrap into the same shape that callers expect
                movie_stub = {
                    "id": match["movie_id"],
                    "title": match["title"],
                    "original_title": match["original_title"],
                    "release_date": str(match.get("year", "")),
                }
                return {
                    "movie": movie_stub,
                    "similarity": {
                        "fuzzy_score": int(match["hybrid_score"] * 100),
                        "hybrid_score": match["hybrid_score"],
                        "jaro_winkler_score": match["jaro_winkler_score"],
                        "bm25_score": match.get("bm25_score", 0.0),
                        "cosine_similarity": match.get("cosine_similarity", 0.0),
                        "exact_match_title": False,
                        "exact_match_original": False,
                    },
                    "score": min(int(match["hybrid_score"] * 100), 100),
                }
        except Exception as e:
            print(f"[hybrid] fallback to thefuzz: {e}")
            # Fall through to standard scoring below

    best_match = None
    best_score = 0

    for movie in filmography:
        similarity = calculate_title_similarity(
            query_title,
            movie.get("title", ""),
            movie.get("original_title", "")
        )

        # Base score from fuzzy matching
        score = similarity["fuzzy_score"]

        # Boost for exact matches
        if similarity["exact_match_original"]:
            score = 100  # Spanish title matches original language title
        elif similarity["exact_match_title"]:
            score = 95   # Title matches localized title

        if score > best_score:
            best_score = score
            best_match = {
                "movie": movie,
                "similarity": similarity,
                "score": min(score, 100)
            }

    return best_match if best_score >= 50 else None


def enrich_movie_with_tmdb(title: str, director: str = "", year: Optional[str] = None) -> dict:
    """
    Full enrichment pipeline for a single movie using TMDB.
    
    Strategy:
    1. Search for director by name
    2. Get their filmography
    3. Find best title match in filmography
    4. Get full movie details
    5. Calculate confidence score
    
    Args:
        title: Movie title from catalog
        director: Director name (optional but recommended)
        year: Release year (optional)
        
    Returns:
        Enrichment result with tmdb_* fields and confidence score
    """
    result = {
        "original_title": title,
        "director": director,
        "enriched": False,
        "tmdb_matched": False,
        "confidence": 0,
        "confidence_breakdown": {},
        "match_type": None,
        "tmdb_movie_id": None,
        "tmdb_title": None,
        "tmdb_original_title": None,
        "tmdb_year": None,
        "data": None
    }
    
    if not director or not director.strip():
        # Without director, we can only do title search (less reliable)
        search_results = search_movie_by_title(title, year)
        if not search_results:
            return result
        
        # Take first result as best guess (low confidence)
        best = search_results[0]
        result["tmdb_movie_id"] = best.get("id")
        result["tmdb_title"] = best.get("title")
        result["tmdb_original_title"] = best.get("original_title")
        result["tmdb_year"] = best.get("release_date", "")[:4] if best.get("release_date") else None
        result["match_type"] = "title_only"
        result["confidence"] = 30  # Low confidence without director verification
        result["confidence_breakdown"] = {"title_only": 30}
        result["tmdb_matched"] = True
        result["enriched"] = True
        result["data"] = best
        return result
    
    # Step 1: Search for director
    person = search_person(director)
    if not person:
        result["match_type"] = "director_not_found"
        return result
    
    person_id = person.get("id")
    
    # Step 2: Get filmography (crew only - movies they directed)
    filmography = get_person_movie_credits(person_id, include_crew=True, include_cast=False)
    if not filmography:
        result["match_type"] = "no_filmography"
        return result
    
    # Step 3: Find best match
    best_match = find_best_match_in_filmography(title, filmography, director)
    if not best_match:
        result["match_type"] = "no_title_match"
        result["confidence_breakdown"] = {"director_confirmed": 30}
        return result
    
    movie = best_match["movie"]
    similarity = best_match["similarity"]
    
    # Step 4: Get full movie details
    details = get_movie_details(movie["id"])
    
    # Step 5: Calculate confidence
    confidence_breakdown = {
        "director_confirmed": 30  # We found the director in TMDB
    }
    
    if similarity["exact_match_original"]:
        confidence_breakdown["title_exact_match_original"] = 40
    elif similarity["exact_match_title"]:
        confidence_breakdown["title_exact_match"] = 40
    
    # Scale fuzzy score to 0-30 points
    fuzzy_contribution = int(similarity["fuzzy_score"] * 0.30)
    confidence_breakdown["title_similarity"] = fuzzy_contribution
    
    total_confidence = sum(confidence_breakdown.values())
    
    # Determine match type
    if similarity["exact_match_original"]:
        match_type = "exact_original"
    elif similarity["exact_match_title"]:
        match_type = "exact_localized"
    elif similarity["fuzzy_score"] >= 80:
        match_type = "high_fuzzy"
    elif similarity["fuzzy_score"] >= 60:
        match_type = "medium_fuzzy"
    else:
        match_type = "low_fuzzy"
    
    result["enriched"] = True
    result["tmdb_matched"] = True
    result["confidence"] = min(total_confidence, 100)
    result["confidence_breakdown"] = confidence_breakdown
    result["match_type"] = match_type
    result["tmdb_movie_id"] = movie["id"]
    result["tmdb_title"] = movie["title"]
    result["tmdb_original_title"] = movie["original_title"]
    result["tmdb_year"] = movie["release_date"][:4] if movie.get("release_date") else None
    result["similarity"] = similarity
    result["data"] = details or movie
    
    return result
