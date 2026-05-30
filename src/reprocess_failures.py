"""
Second-pass reprocessing of failed matches from pending_review.json.
Applies more aggressive cleaning strategies before giving up.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from omdb_client import search_movie_bilingual, get_movie_details, broad_search_movie, find_best_fuzzy_match, search_movie_id, search_director_filmography
from source_of_truth import lookup_movie, update_movie

PENDING_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results', 'pending_review.json')
RATE_LIMIT_DELAY = 0.25
HIGH_CONFIDENCE_TYPES = {'exact_spanish', 'no_article', 'english_fallback', 'source_of_truth', 'exact'}


def is_high_confidence(match_type: str) -> bool:
    if not match_type:
        return False
    for t in HIGH_CONFIDENCE_TYPES:
        if match_type == t or match_type.startswith(t):
            return True
    m = re.match(r'fuzzy_(\d+)', match_type)
    if m and int(m.group(1)) >= 90:
        return True
    return False


def clean_title_aggressive(title: str) -> list[str]:
    """Generate multiple cleaned variants of a messy title."""
    variants = []

    # 1. Remove trailing director/writer noise
    t = re.sub(r'\s*(Dir\.|Guión|Escrita|escritor|prod\.|Director)[^\w]*.*$', '', title, flags=re.IGNORECASE).strip()
    if t and t != title:
        variants.append(t)

    # 2. Remove bracketed content like [i.e. X]
    t2 = re.sub(r'\[.*?\]', '', title).strip()
    if t2 and t2 != title:
        variants.append(t2)

    # 3. Take only first part before space+director name or year
    t3 = re.sub(r'\s+[A-Z][a-z]+ [A-Z][a-z]+,.*$', '', title).strip()  # "Reynolds, Kevin, 1952-"
    if t3 and t3 != title and len(t3) > 3:
        variants.append(t3)

    # 4. Strip parenthetical alt title  
    t4 = re.sub(r'\s*\(.*?\)', '', title).strip()
    if t4 and t4 != title and len(t4) > 3:
        variants.append(t4)

    # 5. Article swap: "Title, El" -> "El Title"
    match = re.search(r'^(.*),\s*(El|La|Los|Las|The|Un|Una)$', title, re.IGNORECASE)
    if match:
        variants.append(f"{match.group(2)} {match.group(1)}".strip())

    # 6. Period between words -> space: "Zona.La" -> "Zona La"  
    t6 = re.sub(r'([a-záéíóúüñA-ZÁÉÍÓÚÜÑ])\.([A-ZÁÉÍÓÚÜÑ])', r'\1 \2', title)
    if t6 != title:
        variants.append(t6)
        # Also try article swap on this
        match2 = re.search(r'^(.*)\s+(El|La|Los|Las)$', t6, re.IGNORECASE)
        if match2:
            variants.append(f"{match2.group(2)} {match2.group(1)}".strip())

    # 7. Remove number in brackets like "Nueve [i.e. 9]" -> "Nine"
    t7 = re.sub(r'\s*\[i\.e\.?\s*\d+\]', '', title).strip()
    if t7 != title:
        variants.append(t7)

    # 8. Take first N words (strip trailing noise)
    words = title.split()
    if len(words) > 5:
        variants.append(' '.join(words[:5]))
    if len(words) > 3:
        variants.append(' '.join(words[:3]))

    # Dedupe while preserving order
    seen = set()
    result = []
    for v in variants:
        v = v.strip().rstrip('.')
        if v and v.lower() not in seen and len(v) > 2:
            seen.add(v.lower())
            result.append(v)
    return result


def try_search_variants(variants: list, director: str = '') -> dict | None:
    for v in variants:
        result = search_movie_bilingual(v)
        if result:
            return result
        time.sleep(RATE_LIMIT_DELAY)
        # Also try broad fuzzy
        candidates = broad_search_movie(v)
        if candidates:
            best = find_best_fuzzy_match(v, candidates)
            if best and best['score'] >= 85:
                return {
                    'imdbID': best['imdbID'],
                    'match_type': f"fuzzy_{best['score']}",
                    'searched_title': v,
                    'matched_title': best['title']
                }
        time.sleep(RATE_LIMIT_DELAY)
    return None


def main():
    with open(PENDING_PATH, 'r', encoding='utf-8') as f:
        pending = json.load(f)

    failed = pending.get('failed_no_match', [])
    fuzzy = pending.get('fuzzy_candidates', [])

    print(f"Re-processing {len(failed)} failed + {len(fuzzy)} fuzzy entries.")

    newly_confirmed = []
    still_failed = []
    still_fuzzy = list(fuzzy)  # carry over existing fuzzy

    for i, entry in enumerate(failed):
        title_es = entry.get('title_spanish', '')
        title_en = entry.get('title_english', '')
        director = entry.get('director', '')
        raw = entry.get('raw_line', '')
        row_id = entry.get('id', '?')

        # Skip if already in SoT (maybe confirmed by another pass)
        if lookup_movie(title_es):
            print(f"[{i+1}/{len(failed)}] id={row_id} SKIP (already in SoT)")
            continue

        print(f"[{i+1}/{len(failed)}] id={row_id} | {title_es[:45]}", end=' ... ', flush=True)

        # Build candidate variants
        variants = []

        # Start with English title if available
        if title_en:
            variants.append(title_en)
            variants.extend(clean_title_aggressive(title_en))

        # Then Spanish variants
        variants.extend(clean_title_aggressive(title_es))
        variants.append(title_es)

        # Dedupe
        seen = set()
        unique_variants = []
        for v in variants:
            if v and v.lower() not in seen:
                seen.add(v.lower())
                unique_variants.append(v)

        result = try_search_variants(unique_variants, director)

        if result:
            imdb_id = result.get('imdbID')
            match_type = result.get('match_type', '')
            matched_title = result.get('matched_title', '')

            if is_high_confidence(match_type):
                details = get_movie_details(imdb_id)
                time.sleep(RATE_LIMIT_DELAY)
                if details:
                    update_movie(title_es, details, match_type=f"reprocess_{match_type}")
                    newly_confirmed.append({
                        'id': row_id, 'title_spanish': title_es,
                        'imdb_id': imdb_id, 'matched_title': details.get('Title'),
                        'match_type': match_type
                    })
                    print(f"✓ {details.get('Title')} ({imdb_id}) [{match_type}]")
                else:
                    still_failed.append(entry)
                    print(f"✗ details fetch failed")
            else:
                still_fuzzy.append({
                    **entry,
                    'candidate_imdb_id': imdb_id,
                    'candidate_title': matched_title,
                    'match_type': match_type
                })
                print(f"? fuzzy: {matched_title} ({imdb_id}) [{match_type}]")
        else:
            # Final fallback: director filmography reasoning
            if director:
                dir_clean = re.sub(r'^(Dir\.|dir\.|Escrita y Dir\.|Guión y Dir\.|prod\. y)\s*', '', director, flags=re.IGNORECASE)
                dir_clean = re.sub(r',\s*\d{4}-?$', '', dir_clean).strip().rstrip('.')
                # Clean title for query
                tq = re.sub(r'([a-záéíóúüñA-ZÁÉÍÓÚÜÑ])\.([A-ZÁÉÍÓÚÜÑ])', r'\1 \2', title_es)
                m2 = re.search(r'^(.*),\s*(El|La|Los|Las|The|Un|Una)\.?$', tq, re.IGNORECASE)
                if m2:
                    tq = f"{m2.group(2)} {m2.group(1)}".strip()
                tq = tq.strip().rstrip('.')

                dir_candidates = search_director_filmography(dir_clean, tq, min_score=65)
                time.sleep(RATE_LIMIT_DELAY)
                # Also try with English title if available and Spanish failed
                if not dir_candidates and title_en:
                    dir_candidates = search_director_filmography(dir_clean, title_en, min_score=65)
                    time.sleep(RATE_LIMIT_DELAY)

                if dir_candidates:
                    best = dir_candidates[0]
                    match_type = f"director_filmography_{best['score']}"
                    if best['score'] >= 90 and best['director_matched']:
                        details = get_movie_details(best['imdbID'])
                        time.sleep(RATE_LIMIT_DELAY)
                        if details:
                            update_movie(title_es, details, match_type=match_type)
                            newly_confirmed.append({
                                'id': row_id, 'title_spanish': title_es,
                                'imdb_id': best['imdbID'],
                                'matched_title': details.get('Title'),
                                'match_type': match_type
                            })
                            print(f"✓ [dir] {details.get('Title')} ({best['imdbID']}) [score={best['score']}, dir={best['director_matched']}]")
                            continue
                    # Low confidence — queue for review with all candidates
                    still_fuzzy.append({
                        **entry,
                        'candidate_imdb_id': best['imdbID'],
                        'candidate_title': best['title'],
                        'match_type': match_type,
                        'director_candidates': dir_candidates[:3]
                    })
                    print(f"? [dir] {best['title']} ({best['imdbID']}) [score={best['score']}, dir={best['director_matched']}]")
                    continue

            still_failed.append(entry)
            print(f"✗ still no match")

    # Save updated pending
    updated_pending = {
        'summary': {
            'newly_confirmed': len(newly_confirmed),
            'fuzzy_review': len(still_fuzzy),
            'failed_no_match': len(still_failed),
        },
        'fuzzy_candidates': still_fuzzy,
        'failed_no_match': still_failed
    }

    with open(PENDING_PATH, 'w', encoding='utf-8') as f:
        json.dump(updated_pending, f, indent=2, ensure_ascii=False)

    print(f"\n=== REPROCESS RESULTS ===")
    print(f"  Newly confirmed : {len(newly_confirmed)}")
    print(f"  Fuzzy (review)  : {len(still_fuzzy)}")
    print(f"  Still failed    : {len(still_failed)}")


if __name__ == '__main__':
    main()
