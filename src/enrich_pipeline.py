"""
Full enrichment pipeline for cine_hybrid_method.csv.

Strategy:
1. Read CSV, skip rows already in SoT.
2. For each row, determine best search title (English > Spanish).
3. Call OMDB via search_movie_bilingual / enrich_movie_with_omdb.
4. High-confidence matches (exact_spanish, no_article, english_fallback, exact, source_of_truth)
   -> confirm to SoT immediately.
5. Fuzzy matches (match_type starts with "fuzzy_") -> collect for manual review.
6. Failures -> collect for individual LLM re-processing.
7. Write pending_review.json for manual inspection.
"""

import csv
import json
import os
import re
import sys
import time
from typing import Optional

# Ensure src/ on path
sys.path.insert(0, os.path.dirname(__file__))

from omdb_client import search_movie_bilingual, get_movie_details, broad_search_movie, find_best_fuzzy_match
from source_of_truth import lookup_movie, update_movie, load_sot

CSV_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results', 'cine_hybrid_method.csv')
PATTERNS_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results', 'title_patterns.json')
PENDING_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results', 'pending_review.json')

HIGH_CONFIDENCE_TYPES = {'exact_spanish', 'no_article', 'english_fallback', 'source_of_truth', 'exact'}
RATE_LIMIT_DELAY = 0.25  # seconds between OMDB calls


def load_patterns() -> dict:
    if os.path.exists(PATTERNS_PATH):
        with open(PATTERNS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return {r['id']: r['patterns'] for r in data.get('row_classifications', [])}
    return {}


def best_search_title(row: dict, patterns: list) -> str:
    """Pick best title to search OMDB with, applying pattern-aware transformations."""
    title_es = row.get('title_spanish', '').strip()
    title_en = row.get('title_english', '').strip()

    # Prefer English title for direct OMDB search
    if title_en:
        # Multi-bilingual chain: take first English-looking segment
        if 'multi_bilingual_chain' in patterns and '=' in title_en:
            parts = [p.strip() for p in title_en.split('=')]
            # Use first part that contains mostly ASCII (likely English/original)
            for part in parts:
                if part and sum(1 for c in part if ord(c) < 128) / max(len(part), 1) > 0.8:
                    return part
        return title_en

    # Spanish-only: apply article swap
    if 'article_swapped' in patterns:
        match = re.search(r'^(.*),\s*(El|La|Los|Las|Un|Una)$', title_es, re.IGNORECASE)
        if match:
            return f"{match.group(2)} {match.group(1)}".strip()

    # Period-joined words: replace period with space
    if 'period_joined_words' in patterns:
        title_es = re.sub(r'([a-záéíóúüñA-ZÁÉÍÓÚÜÑ])\.([A-ZÁÉÍÓÚÜÑ])', r'\1 \2', title_es)

    return title_es


def search_with_fallbacks(row: dict, patterns: list) -> Optional[dict]:
    """Multi-strategy search for a single row."""
    title_es = row.get('title_spanish', '').strip()
    title_en = row.get('title_english', '').strip()
    director = row.get('director', '').strip()

    # Strategy 1: best title
    primary = best_search_title(row, patterns)
    result = search_movie_bilingual(primary)
    if result:
        return result

    time.sleep(RATE_LIMIT_DELAY)

    # Strategy 2: if bilingual, try Spanish side too
    if title_en and title_es and primary != title_es:
        # Apply article swap on Spanish
        es_search = title_es
        match = re.search(r'^(.*),\s*(El|La|Los|Las|Un|Una)$', title_es, re.IGNORECASE)
        if match:
            es_search = f"{match.group(2)} {match.group(1)}".strip()
        result = search_movie_bilingual(es_search)
        if result:
            return result
        time.sleep(RATE_LIMIT_DELAY)

    # Strategy 3: parenthetical alt title
    if 'parenthetical_alt_title' in patterns:
        paren_match = re.search(r'\(([^)]+)\)', title_es)
        if paren_match:
            alt = paren_match.group(1).strip()
            result = search_movie_bilingual(alt)
            if result:
                return result
            time.sleep(RATE_LIMIT_DELAY)

    # Strategy 4: broad fuzzy with director hint
    search_q = primary
    candidates = broad_search_movie(search_q)
    if candidates:
        best = find_best_fuzzy_match(search_q, candidates)
        if best and best['score'] > 65:
            return {
                'imdbID': best['imdbID'],
                'match_type': f"fuzzy_{best['score']}",
                'searched_title': search_q,
                'matched_title': best['title']
            }

    return None


def is_high_confidence(match_type: str) -> bool:
    if not match_type:
        return False
    for t in HIGH_CONFIDENCE_TYPES:
        if match_type == t or match_type.startswith(t):
            return True
    # fuzzy >= 90 counts as high confidence
    m = re.match(r'fuzzy_(\d+)', match_type)
    if m and int(m.group(1)) >= 90:
        return True
    return False


def run_pipeline(start_id: int = 1, end_id: int = 9999, dry_run: bool = False):
    # Load patterns
    patterns_by_id = load_patterns()

    # Load existing SoT
    sot = load_sot()
    print(f"SoT has {len(sot)} existing entries.")

    # Load CSV
    rows = []
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_id = int(row.get('id', 0))
            if start_id <= row_id <= end_id:
                rows.append(row)

    print(f"Processing {len(rows)} rows (id {start_id}..{end_id}).")

    confirmed = []
    fuzzy_review = []
    failed = []
    skipped = 0

    for i, row in enumerate(rows):
        title_es = row.get('title_spanish', '').strip()
        row_id = row.get('id', '?')
        patterns = patterns_by_id.get(row_id, [])

        # Skip if already in SoT
        if lookup_movie(title_es):
            skipped += 1
            continue

        print(f"[{i+1}/{len(rows)}] id={row_id} | {title_es[:50]}", end=' ... ', flush=True)

        result = search_with_fallbacks(row, patterns)
        time.sleep(RATE_LIMIT_DELAY)

        if result:
            imdb_id = result.get('imdbID')
            match_type = result.get('match_type', '')
            matched_title = result.get('matched_title', '')

            if is_high_confidence(match_type):
                if not dry_run:
                    # Fetch full details and confirm to SoT
                    details = get_movie_details(imdb_id)
                    time.sleep(RATE_LIMIT_DELAY)
                    if details:
                        update_movie(title_es, details, match_type=match_type)
                        confirmed.append({
                            'id': row_id,
                            'title_spanish': title_es,
                            'imdb_id': imdb_id,
                            'matched_title': details.get('Title'),
                            'match_type': match_type
                        })
                        print(f"✓ {details.get('Title')} ({imdb_id}) [{match_type}]")
                    else:
                        failed.append({'id': row_id, 'title_spanish': title_es, 'reason': 'details_fetch_failed', 'imdb_id': imdb_id})
                        print(f"✗ details fetch failed for {imdb_id}")
                else:
                    confirmed.append({'id': row_id, 'title_spanish': title_es, 'imdb_id': imdb_id, 'match_type': match_type})
                    print(f"[DRY] ✓ {imdb_id} [{match_type}]")
            else:
                # Fuzzy match — queue for review
                fuzzy_review.append({
                    'id': row_id,
                    'title_spanish': title_es,
                    'title_english': row.get('title_english', ''),
                    'director': row.get('director', ''),
                    'patterns': patterns,
                    'candidate_imdb_id': imdb_id,
                    'candidate_title': matched_title,
                    'match_type': match_type,
                    'raw_line': row.get('raw_line', '')
                })
                print(f"? fuzzy: {matched_title} ({imdb_id}) [{match_type}]")
        else:
            failed.append({
                'id': row_id,
                'title_spanish': title_es,
                'title_english': row.get('title_english', ''),
                'director': row.get('director', ''),
                'patterns': patterns,
                'reason': 'no_match',
                'raw_line': row.get('raw_line', '')
            })
            print(f"✗ no match")

    # Save pending review file
    pending = {
        'summary': {
            'confirmed': len(confirmed),
            'fuzzy_review': len(fuzzy_review),
            'failed': len(failed),
            'skipped_already_in_sot': skipped,
            'total_processed': len(rows)
        },
        'fuzzy_candidates': fuzzy_review,
        'failed_no_match': failed
    }

    if not dry_run:
        with open(PENDING_PATH, 'w', encoding='utf-8') as f:
            json.dump(pending, f, indent=2, ensure_ascii=False)
        print(f"\nPending review saved to {PENDING_PATH}")

    print(f"\n=== RESULTS ===")
    print(f"  Confirmed to SoT : {len(confirmed)}")
    print(f"  Fuzzy (review)   : {len(fuzzy_review)}")
    print(f"  Failed (no match): {len(failed)}")
    print(f"  Skipped (in SoT) : {skipped}")
    print(f"  Total processed  : {len(rows)}")

    return pending


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=int, default=1)
    parser.add_argument('--end', type=int, default=9999)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    run_pipeline(start_id=args.start, end_id=args.end, dry_run=args.dry_run)
