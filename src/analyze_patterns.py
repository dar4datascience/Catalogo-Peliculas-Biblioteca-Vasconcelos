"""
Scan cine_hybrid_method.csv and classify each row into pattern categories.
Outputs data/intermediate_results/title_patterns.json.
"""

import csv
import json
import re
import os
from collections import defaultdict

CSV_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results', 'cine_hybrid_method.csv')
OUT_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results', 'title_patterns.json')

ARTICLE_SUFFIX = re.compile(r',\s*(El|La|Los|Las|The|Le|Les|Der|Die|Das|Un|Una)$', re.IGNORECASE)
SINGLE_TOKEN_DIR = re.compile(r'^\s*[^,\s]+\s*$')


def detect_patterns(row: dict) -> list[str]:
    patterns = []
    title_es = row.get('title_spanish', '').strip()
    title_en = row.get('title_english', '').strip()
    director = row.get('director', '').strip()
    raw = row.get('raw_line', '').strip()

    # 1. Article-swapped title: "Aldea, La"
    if ARTICLE_SUFFIX.search(title_es):
        patterns.append('article_swapped')

    # 2. No English title
    if not title_en:
        patterns.append('spanish_only')

    # 3. Duplicate Spanish title (detected post-hoc, flag here as potential)
    # Will be resolved after full pass — skip for per-row

    # 4. Bilingual chain with multiple = in raw_line
    eq_count = raw.count('=')
    if eq_count >= 2:
        patterns.append('multi_bilingual_chain')
    elif eq_count == 1:
        patterns.append('bilingual_equals')

    # 5. Truncated director: ends with single capital letter (with or without dot)
    #    e.g. "William A", "John R.", "M"
    if director:
        last_token = director.strip().split()[-1]
        if re.match(r'^[A-ZÁÉÍÓÚÜÑ]\.?$', last_token):
            patterns.append('truncated_director')
        # Single-char director (e.g. "M")
        if re.match(r'^[A-ZÁÉÍÓÚÜÑ]\.?$', director.strip()):
            patterns.append('truncated_director')
    else:
        patterns.append('no_director')

    # 6. Multi-director: comma in director field (exclude "Surname, Name" format)
    if director and ',' in director:
        # Check if it looks like "LastName, FirstName" (single person) vs multiple directors
        parts = [p.strip() for p in director.split(',')]
        # If more than 2 parts, definitely multi
        if len(parts) > 2:
            patterns.append('multi_director')
        else:
            # 2 parts: could be "Reiner, Rob" or "Joost, Schulman"
            # Heuristic: if second part looks like a full name (has space or is long), multi
            if ' ' in parts[1] or len(parts[1].split()) > 1:
                patterns.append('multi_director')
            # else treat as swapped "Surname, Firstname" — not multi

    # 7. OCR / encoding artifact in title_spanish
    # Signs: repeated chars, obvious typos, mixed encoding
    if re.search(r'(.)\1{2,}', title_es):  # triple repeated char
        patterns.append('ocr_artifact')
    if re.search(r'[^\x00-\x7FÁÉÍÓÚÜÑáéíóúüñ¿¡]', title_es):
        patterns.append('encoding_artifact')

    # 8. Title contains parenthetical English alt title (no = separator)
    if re.search(r'\(.+\)', title_es) and not title_en:
        patterns.append('parenthetical_alt_title')

    # 9. Title contains period mid-word (OCR artifact: "Año.El")
    if re.search(r'[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]\.[A-ZÁÉÍÓÚÜÑ]', title_es):
        patterns.append('period_joined_words')

    # 10. Director field contains "y" (Spanish "and") — joint director
    if re.search(r'\by\b', director, re.IGNORECASE):
        patterns.append('joint_director_y')

    return list(dict.fromkeys(patterns))  # dedupe, preserve order


def main():
    rows = []
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    pattern_counts = defaultdict(int)
    pattern_examples = defaultdict(list)
    row_patterns = []
    duplicate_spanish = defaultdict(list)

    for row in rows:
        patterns = detect_patterns(row)
        row_id = row.get('id', '')
        title_es = row.get('title_spanish', '')
        duplicate_spanish[title_es].append(row_id)

        row_patterns.append({
            'id': row_id,
            'title_spanish': title_es,
            'title_english': row.get('title_english', ''),
            'director': row.get('director', ''),
            'patterns': patterns
        })

        for p in patterns:
            pattern_counts[p] += 1
            if len(pattern_examples[p]) < 5:
                pattern_examples[p].append({
                    'id': row_id,
                    'title_spanish': title_es,
                    'title_english': row.get('title_english', ''),
                    'director': row.get('director', ''),
                    'raw_line': row.get('raw_line', '')
                })

    # Post-pass: mark duplicate Spanish titles
    dup_titles = {t: ids for t, ids in duplicate_spanish.items() if len(ids) > 1}
    dup_count = 0
    for entry in row_patterns:
        if entry['title_spanish'] in dup_titles:
            if 'duplicate_spanish_title' not in entry['patterns']:
                entry['patterns'].append('duplicate_spanish_title')
                dup_count += 1
                if len(pattern_examples['duplicate_spanish_title']) < 5:
                    pattern_examples['duplicate_spanish_title'].append({
                        'id': entry['id'],
                        'title_spanish': entry['title_spanish'],
                        'title_english': entry['title_english'],
                        'director': entry['director'],
                        'shared_ids': dup_titles[entry['title_spanish']]
                    })
    pattern_counts['duplicate_spanish_title'] = dup_count

    # Summary stats
    total = len(rows)
    clean = sum(1 for r in row_patterns if not r['patterns'])

    output = {
        'summary': {
            'total_rows': total,
            'rows_with_no_patterns': clean,
            'rows_with_patterns': total - clean,
            'duplicate_spanish_titles_groups': len(dup_titles),
            'duplicate_spanish_titles_rows': dup_count
        },
        'pattern_counts': dict(sorted(pattern_counts.items(), key=lambda x: -x[1])),
        'pattern_examples': {k: v for k, v in pattern_examples.items()},
        'pattern_definitions': {
            'article_swapped': 'title_spanish ends with ", El/La/Los/Las/..." — article at end instead of front',
            'spanish_only': 'No English title available — OMDB search must use Spanish title',
            'bilingual_equals': 'raw_line contains one "=" separator between Spanish and English/other title',
            'multi_bilingual_chain': 'raw_line contains 2+ "=" separators — title has 3+ language variants',
            'truncated_director': 'director field ends with single capital letter (initial only), name cut off in PDF',
            'no_director': 'director field is empty',
            'multi_director': 'director field contains multiple people separated by comma',
            'joint_director_y': 'director field contains Spanish "y" (and) — two co-directors',
            'ocr_artifact': 'title_spanish contains triple-repeated character — likely OCR error',
            'encoding_artifact': 'title_spanish contains non-standard characters outside expected Spanish unicode range',
            'parenthetical_alt_title': 'title_spanish contains parenthetical with alt title, no "=" separator',
            'period_joined_words': 'title_spanish has period between words with no space — PDF extraction artifact',
            'duplicate_spanish_title': 'Same title_spanish appears on multiple rows with different English titles/directors'
        },
        'omdb_strategies': {
            'article_swapped': 'Move article to front: "Aldea, La" -> "La Aldea" before OMDB search',
            'spanish_only': 'Search Spanish title directly; fall back to fuzzy broad search',
            'bilingual_equals': 'Extract English part (after "=") for direct OMDB search',
            'multi_bilingual_chain': 'Try each "=" segment independently; use longest English-looking segment first',
            'truncated_director': 'Use raw_line to recover full director name for disambiguation',
            'no_director': 'Title-only search; use year hint if available',
            'multi_director': 'Use first director only for OMDB director field matching',
            'joint_director_y': 'Split on " y " and use first director name',
            'ocr_artifact': 'Use mcp0_analyze_and_match_movie for LLM normalization before search',
            'encoding_artifact': 'Use mcp0_analyze_and_match_movie for LLM normalization before search',
            'parenthetical_alt_title': 'Extract parenthetical content as alt title; try both variants',
            'period_joined_words': 'Replace "." with " " in title before search',
            'duplicate_spanish_title': 'Use title_english + director to disambiguate; match both rows separately'
        },
        'row_classifications': row_patterns
    }

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Total rows: {total}")
    print(f"Clean rows (no patterns): {clean}")
    print(f"Rows with patterns: {total - clean}")
    print("\nPattern counts:")
    for p, c in sorted(pattern_counts.items(), key=lambda x: -x[1]):
        print(f"  {p}: {c}")
    print(f"\nDuplicate Spanish title groups: {len(dup_titles)}")
    if dup_titles:
        print("  Examples:")
        for t, ids in list(dup_titles.items())[:5]:
            print(f"    '{t}' -> rows {ids}")
    print(f"\nSaved to {OUT_PATH}")


if __name__ == '__main__':
    main()
