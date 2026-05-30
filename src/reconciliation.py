"""
Reconciliation module for comparing OMDB vs TMDB movie matches.
Provides confidence scoring and reasoning tools to determine the best match.
"""

import os
import json
from typing import Optional, Dict, List, Any
from pathlib import Path
from thefuzz import fuzz

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
FINAL_DIR = DATA_DIR / "final_results"
CATALOG_FILE = FINAL_DIR / "catalog.json"
TMDB_CATALOG_FILE = FINAL_DIR / "catalog_tmdb.json"
CONFLICTS_FILE = FINAL_DIR / "conflicts_for_review.json"


def normalize_title(title: str) -> str:
    """Normalize title for comparison."""
    if not title:
        return ""
    return ' '.join(title.lower().strip().split())


def calculate_match_confidence(
    raw_title: str,
    matched_title: str,
    matched_original_title: str = "",
    director: str = "",
    source: str = "omdb",  # "omdb" or "tmdb"
    match_type: str = ""
) -> Dict:
    """
    Calculate confidence score for a match based on the formula:
    - Title exact match (Spanish or English): 40 points
    - Director confirmed: 30 points
    - Title similarity (fuzzy ratio * 0.30): 0-30 points
    - English fallback bonus: 10 points (if applicable)
    
    Args:
        raw_title: Original title from catalog
        matched_title: Matched title (localized/English)
        matched_original_title: Original language title (TMDB only)
        director: Director name from catalog
        source: "omdb" or "tmdb"
        match_type: Original match type string from enrichment
        
    Returns:
        Dict with total confidence (0-100) and breakdown
    """
    raw_norm = normalize_title(raw_title)
    matched_norm = normalize_title(matched_title)
    original_norm = normalize_title(matched_original_title)
    
    breakdown = {}
    
    # 1. Title exact match check (40 points)
    exact_match = False
    if raw_norm == matched_norm:
        exact_match = True
        breakdown["title_exact_match_localized"] = 40
    elif source == "tmdb" and original_norm and raw_norm == original_norm:
        exact_match = True
        breakdown["title_exact_match_original"] = 40
    
    # 2. Director confirmed (30 points) - this is determined by the source
    # OMDB: director field in response matches our director
    # TMDB: we searched by director filmography, so it's confirmed
    director_confirmed = False
    if source == "tmdb":
        # TMDB matches are found via director filmography, so director is confirmed
        director_confirmed = bool(director and director.strip())
        if director_confirmed:
            breakdown["director_confirmed"] = 30
    else:
        # For OMDB, we'd need to check the actual response
        # This is handled in compare_matches function
        pass
    
    # 3. Title similarity (0-30 points scaled from 0-100 fuzzy)
    best_fuzzy = fuzz.ratio(raw_norm, matched_norm)
    if source == "tmdb" and original_norm:
        fuzzy_vs_original = fuzz.ratio(raw_norm, original_norm)
        best_fuzzy = max(best_fuzzy, fuzzy_vs_original)
    
    similarity_score = int(best_fuzzy * 0.30)
    breakdown["title_similarity"] = similarity_score
    
    # 4. English fallback bonus (10 points)
    # Check if this was an English fallback match
    if match_type and "english_fallback" in match_type.lower():
        breakdown["english_fallback_bonus"] = 10
    
    total = sum(breakdown.values())
    
    return {
        "confidence": min(total, 100),
        "breakdown": breakdown,
        "exact_match": exact_match,
        "fuzzy_score": best_fuzzy,
        "director_confirmed": director_confirmed
    }


def load_catalog_data() -> tuple:
    """Load both OMDB and TMDB catalog data."""
    omdb_data = {}
    tmdb_data = {}
    
    # Load OMDB catalog
    if CATALOG_FILE.exists():
        with open(CATALOG_FILE, 'r', encoding='utf-8') as f:
            catalog = json.load(f)
            for movie in catalog.get("movies", []):
                title = movie.get("title", "").strip()
                if title:
                    omdb_data[title] = movie
    
    # Load TMDB catalog
    if TMDB_CATALOG_FILE.exists():
        with open(TMDB_CATALOG_FILE, 'r', encoding='utf-8') as f:
            catalog = json.load(f)
            for movie in catalog.get("movies", []):
                title = movie.get("title_spanish", movie.get("original_title", "")).strip()
                if title:
                    tmdb_data[title] = movie
    
    return omdb_data, tmdb_data


def compare_matches(
    raw_title: str,
    director_hint: str = "",
    omdb_data: Dict = None,
    tmdb_data: Dict = None
) -> Dict:
    """
    Compare OMDB and TMDB matches for a specific movie.
    
    Args:
        raw_title: Movie title from catalog
        director_hint: Optional director name
        omdb_data: Pre-loaded OMDB catalog dict (title -> movie)
        tmdb_data: Pre-loaded TMDB catalog dict (title -> movie)
        
    Returns:
        Structured comparison with confidence scores and recommendation
    """
    # Load catalogs if not provided
    if omdb_data is None or tmdb_data is None:
        omdb_data, tmdb_data = load_catalog_data()
    
    result = {
        "raw_title": raw_title,
        "director": director_hint,
        "omdb_match": None,
        "tmdb_match": None,
        "recommendation": "",
        "action": "unknown",
        "conflict": False,
        "reasoning": ""
    }
    
    # Get OMDB result
    omdb_movie = omdb_data.get(raw_title)
    if omdb_movie and omdb_movie.get("enriched"):
        # Calculate OMDB confidence
        omdb_conf = calculate_match_confidence(
            raw_title=raw_title,
            matched_title=omdb_movie.get("matched_title", ""),
            director=director_hint,
            source="omdb",
            match_type=omdb_movie.get("match_type", "")
        )
        
        # Check if director matches (additional verification)
        omdb_director = omdb_movie.get("director", "")
        director_matches = False
        if director_hint and omdb_director:
            director_hint_norm = normalize_title(director_hint)
            omdb_director_norm = normalize_title(omdb_director)
            # Check if any part of our director name appears in OMDB director
            for part in director_hint_norm.split():
                if len(part) > 2 and part in omdb_director_norm:
                    director_matches = True
                    break
        
        if director_matches and "director_confirmed" not in omdb_conf["breakdown"]:
            omdb_conf["breakdown"]["director_confirmed"] = 30
            omdb_conf["confidence"] = min(sum(omdb_conf["breakdown"].values()), 100)
        
        result["omdb_match"] = {
            "imdb_id": omdb_movie.get("imdb_id"),
            "title": omdb_movie.get("matched_title"),
            "year": omdb_movie.get("year"),
            "director": omdb_movie.get("director"),
            "confidence": omdb_conf["confidence"],
            "confidence_breakdown": omdb_conf["breakdown"],
            "match_type": omdb_movie.get("match_type"),
            "poster": omdb_movie.get("poster"),
            "plot_preview": (omdb_movie.get("plot", "")[:100] + "...") if omdb_movie.get("plot") else None
        }
    
    # Get TMDB result
    tmdb_movie = tmdb_data.get(raw_title)
    if tmdb_movie and tmdb_movie.get("tmdb_matched"):
        tmdb_conf = calculate_match_confidence(
            raw_title=raw_title,
            matched_title=tmdb_movie.get("tmdb_title", ""),
            matched_original_title=tmdb_movie.get("tmdb_original_title", ""),
            director=director_hint,
            source="tmdb",
            match_type=tmdb_movie.get("match_type", "")
        )
        
        result["tmdb_match"] = {
            "tmdb_id": tmdb_movie.get("tmdb_movie_id"),
            "title": tmdb_movie.get("tmdb_title"),
            "original_title": tmdb_movie.get("tmdb_original_title"),
            "year": tmdb_movie.get("tmdb_year"),
            "director": tmdb_movie.get("director"),
            "confidence": tmdb_conf["confidence"],
            "confidence_breakdown": tmdb_conf["breakdown"],
            "match_type": tmdb_movie.get("match_type"),
            "similarity_details": tmdb_movie.get("similarity")
        }
    
    # Generate reasoning and recommendation
    omdb_conf_val = result["omdb_match"]["confidence"] if result["omdb_match"] else 0
    tmdb_conf_val = result["tmdb_match"]["confidence"] if result["tmdb_match"] else 0
    
    # Check if they match the same movie
    same_movie = False
    if result["omdb_match"] and result["tmdb_match"]:
        # Compare titles
        omdb_title_norm = normalize_title(result["omdb_match"]["title"])
        tmdb_title_norm = normalize_title(result["tmdb_match"]["title"])
        tmdb_orig_norm = normalize_title(result["tmdb_match"]["original_title"])
        
        if omdb_title_norm == tmdb_title_norm or omdb_title_norm == tmdb_orig_norm:
            same_movie = True
        elif fuzz.ratio(omdb_title_norm, tmdb_title_norm) > 80:
            same_movie = True
    
    if not result["omdb_match"] and not result["tmdb_match"]:
        result["recommendation"] = "No matches found in either OMDB or TMDB. Manual review required."
        result["action"] = "manual_review"
        result["reasoning"] = "Both OMDB and TMDB pipelines failed to find a match. Consider searching with different title variations or checking if the movie exists in databases."
    
    elif not result["omdb_match"]:
        result["recommendation"] = f"Use TMDB match ({result['tmdb_match']['title']}) - OMDB found no match."
        result["action"] = "proceed_with_tmdb"
        result["reasoning"] = f"TMDB found a match with {tmdb_conf_val}% confidence via director {result['tmdb_match']['director']}'s filmography. OMDB returned no results."
    
    elif not result["tmdb_match"]:
        result["recommendation"] = f"Use OMDB match ({result['omdb_match']['title']}) - TMDB found no match."
        result["action"] = "proceed_with_omdb"
        result["reasoning"] = f"OMDB found a match with {omdb_conf_val}% confidence. TMDB director search did not yield a match."
    
    elif same_movie:
        # Both APIs agree on the same movie
        if omdb_conf_val >= 90 and tmdb_conf_val >= 90:
            result["recommendation"] = f"Both APIs agree on '{result['omdb_match']['title']}' with high confidence ({omdb_conf_val}% OMDB, {tmdb_conf_val}% TMDB)."
            result["action"] = "auto_accept"
            result["reasoning"] = "Both OMDB and TMDB returned the same movie with high confidence scores. This is a strong match."
        elif omdb_conf_val >= tmdb_conf_val:
            result["recommendation"] = f"Both APIs agree on '{result['omdb_match']['title']}' - OMDB confidence ({omdb_conf_val}%) >= TMDB ({tmdb_conf_val}%)."
            result["action"] = "proceed_with_omdb"
            result["reasoning"] = "Both APIs identified the same movie. OMDB has equal or higher confidence."
        else:
            result["recommendation"] = f"Both APIs agree on '{result['omdb_match']['title']}' - TMDB confidence ({tmdb_conf_val}%) > OMDB ({omdb_conf_val}%)."
            result["action"] = "proceed_with_tmdb"
            result["reasoning"] = "Both APIs identified the same movie. TMDB has higher confidence via director filmography."
    
    else:
        # Conflict - different movies
        result["conflict"] = True
        
        if tmdb_conf_val > omdb_conf_val + 10:
            result["recommendation"] = f"CONFLICT: TMDB suggests '{result['tmdb_match']['title']}' ({tmdb_conf_val}%) over OMDB's '{result['omdb_match']['title']}' ({omdb_conf_val}%). TMDB match found via director filmography is more likely."
            result["action"] = "prefer_tmdb_review"
            result["reasoning"] = f"The APIs disagree on the match. TMDB found '{result['tmdb_match']['original_title'] or result['tmdb_match']['title']}' in director {result['tmdb_match']['director']}'s filmography with {tmdb_conf_val}% confidence. OMDB returned '{result['omdb_match']['title']}' with {omdb_conf_val}% confidence. The TMDB match via verified director filmography is likely more reliable."
        elif omdb_conf_val > tmdb_conf_val + 10:
            result["recommendation"] = f"CONFLICT: OMDB suggests '{result['omdb_match']['title']}' ({omdb_conf_val}%) over TMDB's '{result['tmdb_match']['title']}' ({tmdb_conf_val}%). OMDB match with higher confidence is preferred."
            result["action"] = "prefer_omdb_review"
            result["reasoning"] = f"The APIs disagree on the match. OMDB returned '{result['omdb_match']['title']}' ({omdb_conf_val}%) while TMDB found '{result['tmdb_match']['original_title'] or result['tmdb_match']['title']}' ({tmdb_conf_val}%) in the director's filmography. OMDB's higher confidence score suggests it may be correct."
        else:
            result["recommendation"] = f"CONFLICT: Close scores - OMDB: '{result['omdb_match']['title']}' ({omdb_conf_val}%), TMDB: '{result['tmdb_match']['title']}' ({tmdb_conf_val}%). Manual decision required."
            result["action"] = "manual_review"
            result["reasoning"] = f"Both APIs returned different movies with similar confidence scores. OMDB: '{result['omdb_match']['title']}' ({omdb_conf_val}%). TMDB: '{result['tmdb_match']['original_title'] or result['tmdb_match']['title']}' from director {result['tmdb_match']['director']}'s filmography ({tmdb_conf_val}%). Please review both options and select the correct match."
    
    return result


def tag_conflict_resolution(
    raw_title: str,
    comparison_result: Dict,
    conflicts_file: str = None
) -> bool:
    """
    Tag a conflict for manual review.
    
    Args:
        raw_title: Movie title
        comparison_result: Result from compare_matches
        conflicts_file: Path to store conflicts
        
    Returns:
        True if tagged successfully
    """
    conflicts_file = conflicts_file or CONFLICTS_FILE
    
    # Only tag actual conflicts
    if not comparison_result.get("conflict"):
        return False
    
    # Load existing conflicts
    conflicts = []
    if os.path.exists(conflicts_file):
        with open(conflicts_file, 'r', encoding='utf-8') as f:
            conflicts = json.load(f)
    
    # Add new conflict
    conflict_entry = {
        "raw_title": raw_title,
        "director": comparison_result.get("director"),
        "omdb_match": comparison_result.get("omdb_match"),
        "tmdb_match": comparison_result.get("tmdb_match"),
        "recommendation": comparison_result.get("recommendation"),
        "reasoning": comparison_result.get("reasoning"),
        "status": "pending_review"
    }
    
    # Check if already exists
    existing = [c for c in conflicts if c["raw_title"] == raw_title]
    if existing:
        # Update existing
        existing[0].update(conflict_entry)
    else:
        conflicts.append(conflict_entry)
    
    # Save
    os.makedirs(os.path.dirname(conflicts_file), exist_ok=True)
    with open(conflicts_file, 'w', encoding='utf-8') as f:
        json.dump(conflicts, f, indent=2, ensure_ascii=False)
    
    return True


def get_all_conflicts(conflicts_file: str = None) -> List[Dict]:
    """Get all tagged conflicts for review."""
    conflicts_file = conflicts_file or CONFLICTS_FILE
    
    if not os.path.exists(conflicts_file):
        return []
    
    with open(conflicts_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def batch_compare_all() -> List[Dict]:
    """
    Compare all movies in the catalog and return results.
    Also tags conflicts for manual review.
    
    Returns:
        List of comparison results for all movies
    """
    omdb_data, tmdb_data = load_catalog_data()
    
    # Get all unique titles
    all_titles = set(omdb_data.keys()) | set(tmdb_data.keys())
    
    results = []
    conflicts_count = 0
    
    print(f"Comparing {len(all_titles)} movies...")
    
    for i, title in enumerate(sorted(all_titles), 1):
        # Try to get director from either source
        director = ""
        if title in tmdb_data:
            director = tmdb_data[title].get("director", "")
        if not director and title in omdb_data:
            director = omdb_data[title].get("director", "")
        
        comparison = compare_matches(title, director, omdb_data, tmdb_data)
        results.append(comparison)
        
        # Tag conflicts
        if comparison.get("conflict"):
            tag_conflict_resolution(title, comparison)
            conflicts_count += 1
        
        if i % 100 == 0:
            print(f"  Processed {i}/{len(all_titles)}... (conflicts: {conflicts_count})")
    
    print(f"\nComparison complete:")
    print(f"  Total: {len(all_titles)}")
    print(f"  Conflicts tagged: {conflicts_count}")
    
    return results


if __name__ == "__main__":
    # Run batch comparison
    results = batch_compare_all()
    
    # Print summary
    auto_accept = sum(1 for r in results if r.get("action") == "auto_accept")
    proceed_omdb = sum(1 for r in results if r.get("action") == "proceed_with_omdb")
    proceed_tmdb = sum(1 for r in results if r.get("action") == "proceed_with_tmdb")
    manual = sum(1 for r in results if "manual_review" in r.get("action", ""))
    conflicts = sum(1 for r in results if r.get("conflict"))
    
    print("\nAction Summary:")
    print(f"  Auto accept: {auto_accept}")
    print(f"  Proceed with OMDB: {proceed_omdb}")
    print(f"  Proceed with TMDB: {proceed_tmdb}")
    print(f"  Manual review: {manual}")
    print(f"  Total conflicts: {conflicts}")
