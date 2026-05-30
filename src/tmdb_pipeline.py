"""
TMDB Pipeline for movie catalog enrichment.
Extracts unique directors from CINE.pdf, fetches their filmographies, and matches catalog movies.
"""

import os
import sys
import json
import re
import csv
from typing import List, Dict, Optional, Set
from pathlib import Path

# Ensure src directory is in path for imports
sys.path.insert(0, os.path.dirname(__file__))

from tmdb_client import (
    search_person,
    get_person_movie_credits,
    get_movie_details,
    enrich_movie_with_tmdb
)
from models import CatalogIndex, Movie

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
INTERMEDIATE_DIR = DATA_DIR / "intermediate_results"
FINAL_DIR = DATA_DIR / "final_results"
CINE_CSV = INTERMEDIATE_DIR / "cine_hybrid_method.csv"
DIRECTOR_CACHE_FILE = FINAL_DIR / "director_filmographies.json"
TMDB_CATALOG_FILE = FINAL_DIR / "catalog_tmdb.json"


def clean_director_name(name: str) -> str:
    """
    Clean director name from CSV, removing common PDF artifacts.
    
    Examples:
    - "Dir. David Cronenberg" -> "David Cronenberg"
    - "Escrita y Dir. Florian Henckel" -> "Florian Henckel"
    - "William A. Graham" -> "William A. Graham" (keep middle initial)
    - "Susanne Bier" -> "Susanne Bier"
    """
    if not name or not name.strip():
        return ""
    
    # Remove common prefixes
    cleaned = re.sub(r'^(Dir\.|dir\.|Escrita y Dir\.|Guión y Dir\.|prod\. y)\s*', '', name, flags=re.IGNORECASE)
    
    # Remove trailing birth/death years and commas
    cleaned = re.sub(r',\s*\d{4}-?\d{0,4}$', '', cleaned)
    cleaned = re.sub(r',\s*\d{4}-?$', '', cleaned)
    
    # Clean up whitespace and trailing punctuation
    cleaned = cleaned.strip().rstrip('.').rstrip(',')
    cleaned = ' '.join(cleaned.split())
    
    return cleaned


def get_unique_directors_from_csv(csv_path: str = None) -> List[str]:
    """
    Parse CINE CSV to extract unique, cleaned director names.
    
    Returns:
        List of unique director names (cleaned)
    """
    csv_path = csv_path or CINE_CSV
    directors: Set[str] = set()
    
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        return []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            director_raw = row.get('director', '').strip()
            if director_raw:
                cleaned = clean_director_name(director_raw)
                if cleaned and len(cleaned) > 2:  # Filter out very short names
                    directors.add(cleaned)
    
    return sorted(list(directors))


def fetch_director_filmography(director: str, use_cache: bool = True, cache_file: str = None) -> Optional[Dict]:
    """
    Fetch a director's complete filmography from TMDB.
    Uses and updates the cache.
    
    Args:
        director: Director name
        use_cache: Whether to check cache first
        cache_file: Path to cache file
        
    Returns:
        Dict with director info and filmography, or None if not found
    """
    cache_file = cache_file or DIRECTOR_CACHE_FILE
    
    # Check cache first
    if use_cache and os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        if director in cache:
            return cache[director]
    
    # Search for person
    person = search_person(director)
    if not person:
        return None
    
    person_id = person.get("id")
    
    # Get filmography
    filmography = get_person_movie_credits(person_id, include_crew=True, include_cast=False)
    
    result = {
        "name": director,
        "tmdb_person_id": person_id,
        "tmdb_name": person.get("name"),
        "popularity": person.get("popularity"),
        "filmography": filmography,
        "movie_count": len(filmography)
    }
    
    # Update cache
    if use_cache:
        cache = {}
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        cache[director] = result
        
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    
    return result


def build_director_cache(directors: List[str] = None, cache_file: str = None) -> Dict:
    """
    Fetch and cache filmographies for all unique directors.
    
    Args:
        directors: List of director names (if None, extracts from CSV)
        cache_file: Path to cache file
        
    Returns:
        Dict mapping director names to their filmographies
    """
    cache_file = cache_file or DIRECTOR_CACHE_FILE
    
    if directors is None:
        directors = get_unique_directors_from_csv()
    
    print(f"Building director cache for {len(directors)} unique directors...")
    
    cache = {}
    not_found = []
    
    for i, director in enumerate(directors, 1):
        print(f"  [{i}/{len(directors)}] Fetching filmography for: {director}")
        
        filmography = fetch_director_filmography(director, use_cache=True, cache_file=cache_file)
        if filmography:
            cache[director] = filmography
        else:
            not_found.append(director)
        
        # Save progress every 10 directors
        if i % 10 == 0:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)
            print(f"  Saved progress: {i} directors cached")
    
    # Final save
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    
    print(f"\nDirector cache complete:")
    print(f"  Found: {len(cache)} directors")
    print(f"  Not found: {len(not_found)} directors")
    if not_found:
        print(f"  Missing: {', '.join(not_found[:10])}{'...' if len(not_found) > 10 else ''}")
    
    return cache


def load_director_cache(cache_file: str = None) -> Dict:
    """Load the director filmography cache from disk."""
    cache_file = cache_file or DIRECTOR_CACHE_FILE
    
    if not os.path.exists(cache_file):
        return {}
    
    with open(cache_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def match_catalog_to_tmdb(csv_path: str = None, cache_file: str = None) -> List[Dict]:
    """
    Match all movies from CINE CSV against TMDB using director filmographies.
    
    Args:
        csv_path: Path to CINE CSV
        cache_file: Path to director cache file
        
    Returns:
        List of enriched movie records
    """
    csv_path = csv_path or CINE_CSV
    cache_file = cache_file or DIRECTOR_CACHE_FILE
    
    # Load director cache
    director_cache = load_director_cache(cache_file)
    if not director_cache:
        print("No director cache found. Building cache first...")
        director_cache = build_director_cache(cache_file=cache_file)
    
    print(f"\nMatching catalog movies against TMDB...")
    
    movies = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    total = len(rows)
    matched = 0
    unmatched = []
    
    for i, row in enumerate(rows, 1):
        title = row.get('title_spanish', '').strip()
        title_english = row.get('title_english', '').strip()
        director_raw = row.get('director', '').strip()
        movie_id = row.get('id', '')
        
        if not title:
            continue
        
        director_clean = clean_director_name(director_raw)
        
        # Enrich with TMDB
        result = enrich_movie_with_tmdb(title, director_clean)
        
        # Add metadata from CSV
        result['catalog_id'] = movie_id
        result['title_spanish'] = title
        result['title_english'] = title_english
        result['director_raw'] = director_raw
        
        # Store the director's cached filmography for reference
        if director_clean in director_cache:
            result['director_filmography_count'] = director_cache[director_clean].get('movie_count', 0)
        
        movies.append(result)
        
        if result['tmdb_matched']:
            matched += 1
        else:
            unmatched.append({
                'id': movie_id,
                'title': title,
                'director': director_clean,
                'reason': result.get('match_type', 'unknown')
            })
        
        if i % 100 == 0:
            print(f"  Processed {i}/{total} movies... (matched: {matched})")
    
    print(f"\nMatching complete:")
    print(f"  Total: {total}")
    print(f"  Matched: {matched} ({matched/total*100:.1f}%)")
    print(f"  Unmatched: {len(unmatched)} ({len(unmatched)/total*100:.1f}%)")
    
    return movies


def calculate_confidence_distribution(movies: List[Dict]) -> Dict:
    """Calculate confidence score distribution across all matches."""
    high = sum(1 for m in movies if m.get('confidence', 0) >= 90 and m.get('tmdb_matched'))
    medium = sum(1 for m in movies if 70 <= m.get('confidence', 0) < 90 and m.get('tmdb_matched'))
    low = sum(1 for m in movies if m.get('confidence', 0) < 70 and m.get('tmdb_matched'))
    unmatched = sum(1 for m in movies if not m.get('tmdb_matched'))
    
    return {
        "90-100% (auto-accept)": high,
        "70-89% (manual review)": medium,
        "0-69% (low confidence)": low,
        "unmatched": unmatched
    }


def run_tmdb_pipeline(output_file: str = None) -> Dict:
    """
    Run the complete TMDB enrichment pipeline.
    
    1. Extract unique directors from CINE.csv
    2. Fetch and cache all director filmographies
    3. Match all catalog movies against TMDB
    4. Calculate statistics
    5. Save results to JSON
    
    Args:
        output_file: Path to output JSON file
        
    Returns:
        Complete results dict with movies and stats
    """
    output_file = output_file or TMDB_CATALOG_FILE
    
    print("=" * 60)
    print("TMDB Movie Catalog Enrichment Pipeline")
    print("=" * 60)
    
    # Step 1: Get unique directors
    print("\n[Step 1] Extracting unique directors from CINE.csv...")
    directors = get_unique_directors_from_csv()
    print(f"  Found {len(directors)} unique directors")
    
    # Step 2: Build director cache
    print("\n[Step 2] Building director filmography cache...")
    director_cache = build_director_cache(directors)
    
    # Step 3: Match all movies
    print("\n[Step 3] Matching catalog movies...")
    movies = match_catalog_to_tmdb()
    
    # Step 4: Calculate statistics
    print("\n[Step 4] Calculating statistics...")
    confidence_dist = calculate_confidence_distribution(movies)
    
    total = len(movies)
    matched = sum(1 for m in movies if m.get('tmdb_matched'))
    
    stats = {
        "total_movies": total,
        "matched_via_tmdb": matched,
        "unmatched": total - matched,
        "match_rate": round(matched / total * 100, 2) if total > 0 else 0,
        "unique_directors": len(directors),
        "directors_cached": len(director_cache),
        "confidence_distribution": confidence_dist
    }
    
    # Step 5: Compile results
    results = {
        "movies": movies,
        "stats": stats,
        "metadata": {
            "source": "TMDB API",
            "pipeline_version": "1.0",
            "enrichment_strategy": "director_filmography_matching"
        }
    }
    
    # Step 6: Save to file
    print(f"\n[Step 5] Saving results to {output_file}...")
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print("\n" + "=" * 60)
    print("Pipeline Complete!")
    print("=" * 60)
    print(f"Total movies: {stats['total_movies']}")
    print(f"Matched: {stats['matched_via_tmdb']} ({stats['match_rate']}%)")
    print(f"Unmatched: {stats['unmatched']}")
    print(f"\nConfidence Distribution:")
    for bucket, count in confidence_dist.items():
        print(f"  {bucket}: {count}")
    
    return results


if __name__ == "__main__":
    # Run the pipeline
    results = run_tmdb_pipeline()
