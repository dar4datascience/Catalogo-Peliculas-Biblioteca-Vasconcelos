"""
Build data/final_results/catalog.json from source_of_truth.json + CINE CSV.
Produces one entry per CINE.pdf row (2,243 total) with full OMDB enrichment
when available, otherwise raw title/director from the CSV.
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from source_of_truth import load_sot

BASE_DIR    = os.path.join(os.path.dirname(__file__), '..')
CINE_CSV    = os.path.join(BASE_DIR, 'data', 'intermediate_results', 'cine_hybrid_method.csv')
OUT_JSON    = os.path.join(BASE_DIR, 'data', 'final_results', 'catalog.json')
SOURCE_PDF  = 'CINE.pdf'
PDF_CATEGORY = 'CINE'


def parse_genres(genre_str: str) -> list[str]:
    if not genre_str or genre_str in ('N/A', 'NA', ''):
        return []
    return [g.strip() for g in genre_str.split(',') if g.strip()]


def safe_str(val) -> str:
    if val in (None, 'N/A', 'NA', ''):
        return ''
    return str(val).strip()


def build_search_text(entry: dict) -> str:
    parts = [
        entry.get('title', ''),
        entry.get('matched_title', ''),
        entry.get('director', ''),
        ' '.join(entry.get('genre', [])),
        entry.get('country', ''),
        entry.get('actors', ''),
        entry.get('year', ''),
    ]
    return ' '.join(p.lower() for p in parts if p).strip()


def main():
    sot = load_sot()
    print(f"SoT entries: {len(sot)}")

    # Build a lookup by normalised title_spanish
    def norm(s: str) -> str:
        return s.strip().lower()

    sot_by_norm = {norm(k): (k, v) for k, v in sot.items()}

    with open(CINE_CSV, encoding='utf-8') as f:
        cine_rows = list(csv.DictReader(f))
    print(f"CINE CSV rows: {len(cine_rows)}")

    movies = []
    enriched_count = 0

    for row in cine_rows:
        cat_id_raw = row.get('id', '').strip()
        catalogue_id = int(cat_id_raw) if cat_id_raw.isdigit() else None
        title_es = row.get('title_spanish', '').strip()
        director_raw = row.get('director', '').strip()

        # Look up in SoT
        match_key = norm(title_es)
        sot_entry = sot_by_norm.get(match_key)

        if sot_entry:
            _, sot_val = sot_entry
            fd = sot_val.get('full_data', {})
            genre_list = parse_genres(fd.get('Genre', ''))
            decade = None
            year_str = safe_str(fd.get('Year', ''))
            if year_str and year_str[:4].isdigit():
                decade = f"{year_str[:3]}0s"

            entry = {
                'catalogue_id':   catalogue_id,
                'title':          title_es,
                'matched_title':  safe_str(sot_val.get('matched_title', fd.get('Title', ''))),
                'imdb_id':        safe_str(sot_val.get('imdb_id', fd.get('imdbID', ''))),
                'year':           year_str,
                'decade':         decade,
                'director':       safe_str(fd.get('Director', director_raw)),
                'writer':         safe_str(fd.get('Writer', '')),
                'actors':         safe_str(fd.get('Actors', '')),
                'plot':           safe_str(fd.get('Plot', '')),
                'language':       safe_str(fd.get('Language', '')),
                'country':        safe_str(fd.get('Country', '')),
                'awards':         safe_str(fd.get('Awards', '')),
                'poster':         safe_str(fd.get('Poster', '')),
                'genre':          genre_list,
                'imdb_rating':    safe_str(fd.get('imdbRating', '')),
                'imdb_votes':     safe_str(fd.get('imdbVotes', '')),
                'metascore':      safe_str(fd.get('Metascore', '')),
                'rated':          safe_str(fd.get('Rated', '')),
                'runtime':        safe_str(fd.get('Runtime', '')),
                'enriched':       True,
                'match_type':     safe_str(sot_val.get('match_type', '')),
                'pdf_category':   PDF_CATEGORY,
                'category_display': PDF_CATEGORY,
                'source_pdf':     SOURCE_PDF,
            }
            entry['search_text'] = build_search_text(entry)
            enriched_count += 1
        else:
            # Unenriched entry
            entry = {
                'catalogue_id':   catalogue_id,
                'title':          title_es,
                'matched_title':  '',
                'imdb_id':        '',
                'year':           '',
                'decade':         None,
                'director':       director_raw,
                'writer':         '',
                'actors':         '',
                'plot':           '',
                'language':       '',
                'country':        '',
                'awards':         '',
                'poster':         '',
                'genre':          [],
                'imdb_rating':    '',
                'imdb_votes':     '',
                'metascore':      '',
                'rated':          '',
                'runtime':        '',
                'enriched':       False,
                'match_type':     'unmatched',
                'pdf_category':   PDF_CATEGORY,
                'category_display': PDF_CATEGORY,
                'source_pdf':     SOURCE_PDF,
            }
            entry['search_text'] = build_search_text(entry)

        movies.append(entry)

    catalog = {
        'metadata': {
            'source':           SOURCE_PDF,
            'total_entries':    len(movies),
            'enriched_entries': enriched_count,
            'unenriched':       len(movies) - enriched_count,
            'enrichment_rate':  round(enriched_count / len(movies) * 100, 1),
        },
        'movies': movies,
    }

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, ensure_ascii=False, separators=(',', ':'))

    size_mb = os.path.getsize(OUT_JSON) / 1_048_576
    print(f"Written: {OUT_JSON}")
    print(f"  Total : {len(movies)}")
    print(f"  Enriched: {enriched_count} ({catalog['metadata']['enrichment_rate']}%)")
    print(f"  Size  : {size_mb:.1f} MB")


if __name__ == '__main__':
    main()
