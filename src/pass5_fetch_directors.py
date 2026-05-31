"""
Pass 5: Fetch missing director filmographies into DuckDB, then re-run TMDB hybrid
match + OMDB confirm on the 272 still-failed entries.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from tmdb_client import search_person, get_person_movie_credits, get_tmdb_external_ids
from tmdb_duckdb import TMDBDuckDB
from omdb_client import get_movie_details, _query_omdb, API_KEY
from source_of_truth import lookup_movie, update_movie

PENDING_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results', 'pending_review.json')
CATALOGUE_NAME = 'CINE.pdf'
TMDB_RATE = 0.26   # ~4 req/s (TMDB free tier allows 40/10s)
OMDB_RATE = 0.4
HYBRID_MIN_CONFIRM = 0.72   # auto-confirm threshold
HYBRID_MIN_FUZZY = 0.58     # add to fuzzy queue if below confirm threshold

DIR_CLEAN_RE = re.compile(
    r'^(Dir\.|dir\.|Escrita y Dir\.|Guión y Dir\.|prod\. y|Directed by|Dirigida? por)\s*',
    re.IGNORECASE
)


def clean_director(raw: str) -> str:
    raw = DIR_CLEAN_RE.sub('', raw).strip()
    # Strip trailing junk like ", 1952-" or "(1952-)"
    raw = re.sub(r',?\s*\d{4}-?\s*$', '', raw).strip()
    # Remove parenthetical years
    raw = re.sub(r'\s*\(\d{4}\)', '', raw).strip()
    return raw


def fetch_and_cache_director(db: TMDBDuckDB, director_name: str) -> bool:
    """
    Search TMDB for director, fetch filmography, insert into DuckDB.
    Returns True if successfully added.
    """
    person = search_person(director_name)
    time.sleep(TMDB_RATE)
    if not person:
        return False

    person_id = person.get('id')
    if not person_id:
        return False

    movies = get_person_movie_credits(person_id, include_crew=True, include_cast=False)
    time.sleep(TMDB_RATE)

    if not movies:
        return False

    tmdb_data = {
        'tmdb_person_id': person_id,
        'popularity': person.get('popularity', 0),
        'movie_count': len(movies),
        'filmography': movies,
    }
    db.add_director(director_name, tmdb_data)
    return True


def is_director_cached(db: TMDBDuckDB, director_name: str) -> bool:
    result = db.conn.execute(
        "SELECT id FROM directors WHERE name = ?", [director_name]
    ).fetchone()
    return result is not None


def main():
    with open(PENDING_PATH, 'r', encoding='utf-8') as f:
        pending = json.load(f)

    failed = pending.get('failed_no_match', [])
    fuzzy_queue = pending.get('fuzzy_candidates', [])
    print(f"Pass 5: {len(failed)} failed entries to process")

    db = TMDBDuckDB()

    # --- Step A: collect unique directors, fetch missing filmographies ---
    directors_needed = {}
    for e in failed:
        raw_dir = e.get('director', '').strip()
        if not raw_dir:
            continue
        cleaned = clean_director(raw_dir)
        if not cleaned:
            continue
        if cleaned not in directors_needed:
            directors_needed[cleaned] = []
        directors_needed[cleaned].append(e)

    print(f"\n[A] Fetching filmographies for {len(directors_needed)} unique directors...")
    fetched, skipped, failed_fetch = 0, 0, 0
    for i, (director, entries) in enumerate(directors_needed.items()):
        if is_director_cached(db, director):
            skipped += 1
            continue
        ok = fetch_and_cache_director(db, director)
        if ok:
            fetched += 1
            print(f"  [{i+1}/{len(directors_needed)}] FETCHED: {director} ({len(entries)} entries)")
        else:
            failed_fetch += 1
            print(f"  [{i+1}/{len(directors_needed)}] NOT FOUND: {director}")

    print(f"\n  Fetched: {fetched} | Already cached: {skipped} | Not found: {failed_fetch}")

    # Rebuild indexes after bulk insert
    if fetched > 0:
        print("\n[A] Rebuilding FTS and HNSW indexes...")
        try:
            db.build_fts_index()
        except Exception as e:
            print(f"  FTS index warning: {e}")
        try:
            db.build_hnsw_index()
        except Exception as e:
            print(f"  HNSW index warning: {e}")

    # --- Step B: Re-run hybrid match on all failed entries ---
    print(f"\n[B] Re-running hybrid match on {len(failed)} failed entries...")
    newly_confirmed = []
    newly_fuzzy = []
    still_failed = []

    for i, entry in enumerate(failed):
        title_es = entry.get('title_spanish', '')
        raw_dir = entry.get('director', '').strip()
        cat_id = entry.get('id')

        # Skip if already in SoT
        if lookup_movie(title_es):
            print(f"  [{i+1}/{len(failed)}] SKIP (already in SoT): {title_es[:40]}")
            continue

        director = clean_director(raw_dir) if raw_dir else ''
        print(f"  [{i+1}/{len(failed)}] {title_es[:45]}", end=' ... ', flush=True)

        if not director:
            still_failed.append(entry)
            print("no director")
            continue

        # Try hybrid match
        match = db.find_best_match_hybrid(title_es, director, min_similarity=HYBRID_MIN_FUZZY)

        if not match:
            still_failed.append(entry)
            print("no TMDB match")
            continue

        score = match.get('hybrid_score', 0)
        tmdb_id = match.get('movie_id')
        matched_title = match.get('title') or match.get('original_title', '')

        if score < HYBRID_MIN_CONFIRM:
            newly_fuzzy.append({
                **entry,
                'candidate_tmdb_id': tmdb_id,
                'candidate_title': matched_title,
                'match_type': f'pass5_tmdb_hybrid_{score:.2f}',
                'hybrid_score': score,
            })
            print(f"fuzzy ({score:.2f}): {matched_title}")
            continue

        # Resolve TMDB → IMDb
        imdb_id = get_tmdb_external_ids(tmdb_id)
        time.sleep(OMDB_RATE)
        if not imdb_id or not imdb_id.startswith('tt'):
            still_failed.append(entry)
            print(f"no IMDb ID for TMDB {tmdb_id}")
            continue

        # Fetch full OMDB data
        omdb_data = _query_omdb({'i': imdb_id, 'apikey': API_KEY})
        time.sleep(OMDB_RATE)
        if not omdb_data:
            still_failed.append(entry)
            print(f"OMDB miss for {imdb_id}")
            continue

        # Confirm to SoT
        update_movie(
            title_es, omdb_data,
            match_type=f'pass5_tmdb_hybrid_{score:.2f}',
            catalogue=CATALOGUE_NAME,
            catalogue_id=int(cat_id) if str(cat_id).isdigit() else None,
            page_number=None,
        )
        newly_confirmed.append({
            'id': cat_id,
            'title_spanish': title_es,
            'imdb_id': imdb_id,
            'matched_title': omdb_data.get('Title'),
            'score': score,
        })
        print(f"CONFIRMED ({score:.2f}): {omdb_data.get('Title')} ({imdb_id})")

    # --- Save updated pending ---
    updated_fuzzy = fuzzy_queue + newly_fuzzy
    updated = {
        'summary': {
            'pass5_newly_confirmed': len(newly_confirmed),
            'fuzzy_review': len(updated_fuzzy),
            'failed_no_match': len(still_failed),
        },
        'fuzzy_candidates': updated_fuzzy,
        'failed_no_match': still_failed,
    }
    with open(PENDING_PATH, 'w', encoding='utf-8') as f:
        json.dump(updated, f, indent=2, ensure_ascii=False)

    db.close()

    print(f"\n=== PASS 5 RESULTS ===")
    print(f"  Newly confirmed : {len(newly_confirmed)}")
    print(f"  Added to fuzzy  : {len(newly_fuzzy)}")
    print(f"  Still failed    : {len(still_failed)}")
    print(f"  Total fuzzy queue: {len(updated_fuzzy)}")


if __name__ == '__main__':
    main()
