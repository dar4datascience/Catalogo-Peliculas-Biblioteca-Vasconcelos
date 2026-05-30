"""
Unified data pipeline for movie catalog.
Combines PDF extraction, OMDB enrichment, and export to ObservableJS format.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from models import CatalogIndex, Movie, PDFSource, ProcessingSummary
from omdb_client import enrich_movie_with_omdb
from pdf_extractor import (
    extract_pdf_metadata,
    extract_tables_from_pdf,
    find_index_page,
)

load_dotenv()

PDF_DIR = Path(__file__).parent.parent / 'data' / 'pdfs'
OUTPUT_DIR = Path(__file__).parent.parent / 'data' / 'final_results'


def clean_title(text: str) -> str:
    """Clean extracted title text."""
    if not isinstance(text, str):
        return ""

    text = text.replace('\n', ' ').strip()
    # Remove leading numbers
    text = re.sub(r'^\d+[\s\.]*', '', text)
    # Remove "N." or "No." prefixes
    text = re.sub(r'^[Nn]\.?[oO]?\s*[\.:]?', '', text)
    # Remove trailing "=..."
    text = re.sub(r'=[^=]*$', '', text)
    # Remove trailing "(...)"
    text = re.sub(r'\([^)]*\)$', '', text)
    return text.strip('",. ')


def is_valid_title(title: str) -> bool:
    """Check if extracted text is a valid movie title."""
    if not title or len(title) < 4 or title.isdigit():
        return False

    invalid_keywords = ['título', 'title', 'director', 'género', 'pagina', 'indice']
    if title.lower() in invalid_keywords:
        return False

    # If it looks like a list of names, it's probably not a title
    if len(re.findall(r'[A-Z][a-z]+', title)) > 4 and ',' in title:
        return False

    # Skip lines with director/credit keywords
    director_keywords = [
        'dir\.', 'prod\.', 'animación', 'aventura', 'comedia',
        'drama', 'fantasía', 'ciencia ficción', 'género',
        'director', 'guión', 'tetsuo', 'katayama',
        'suzuki', 'yoshiaki', 'hayao', 'miyazaki', 'takahata', 'goro'
    ]

    if any(re.search(keyword, title, re.IGNORECASE) for keyword in director_keywords):
        return False

    return True


def get_category_from_filename(filename: str) -> str:
    """Extract category from PDF filename."""
    # Remove .pdf extension
    name = filename.replace('.pdf', '')
    # Common category patterns
    return name.strip()


def extract_movies_from_pdf(pdf_path: Path) -> tuple[list[Movie], PDFSource]:
    """
    Extract movies from a single PDF file.

    Returns:
        Tuple of (list of Movie objects, PDFSource metadata)
    """
    print(f"Processing {pdf_path.name}...")

    # Get PDF metadata
    pdf_meta = extract_pdf_metadata(str(pdf_path))
    category = get_category_from_filename(pdf_path.name)

    pdf_source = PDFSource(
        file_name=pdf_path.name,
        category=category,
        page_count=pdf_meta.get('page_count', 0),
        has_index=find_index_page(str(pdf_path)) >= 0
    )

    # Extract tables
    tables = extract_tables_from_pdf(str(pdf_path))
    movies = []
    seen_titles = set()

    for i, df in enumerate(tables):
        if df.empty:
            continue

        # Focus on first column (titles usually in first column)
        for item in df.iloc[:, 0]:
            cleaned = clean_title(str(item))
            if is_valid_title(cleaned) and cleaned not in seen_titles:
                movie = Movie(
                    title=cleaned,
                    source_pdf=pdf_path.name,
                    pdf_category=category
                )
                movies.append(movie)
                seen_titles.add(cleaned)

    print(f"  Extracted {len(movies)} movies from {pdf_path.name}")
    return movies, pdf_source


def enrich_movie(movie: Movie, use_llm: bool = True) -> Movie:
    """Enrich a single movie with OMDB data."""
    if use_llm:
        # Use LLM-enhanced enrichment for better match rates
        from llm_enrichment import enhanced_enrich_movie
        return enhanced_enrich_movie(movie)
    else:
        # Use basic enrichment
        result = enrich_movie_with_omdb(
            title=movie.title,
            source_pdf=movie.source_pdf
        )

        if result['enriched']:
            movie.enriched = True
            movie.match_type = result.get('match_type')
            movie.searched_title = result.get('searched_title')
            movie.matched_title = result.get('matched_title')

            # Map OMDB fields
            movie.imdb_id = result['data'].get('imdbID')
            movie.year = result['data'].get('Year')
            movie.director = result.get('director')
            movie.writer = result['data'].get('Writer')
            movie.actors = result['data'].get('Actors')
            movie.plot = result.get('plot')
            movie.language = result['data'].get('Language')
            movie.country = result.get('country')
            movie.awards = result['data'].get('Awards')
            movie.poster = result.get('poster')
            movie.imdb_rating = result.get('imdb_rating')
            movie.imdb_votes = result['data'].get('imdbVotes')
            movie.metascore = result['data'].get('Metascore')

            # Parse genre
            genre_str = result['data'].get('Genre', '')
            if genre_str:
                movie.genre = [g.strip() for g in genre_str.split(',')]

        return movie


def process_all_pdfs(max_workers: int = 5) -> CatalogIndex:
    """
    Process all PDFs and return complete catalog.

    Args:
        max_workers: Number of parallel threads for OMDB enrichment.

    Returns:
        CatalogIndex with all movies and metadata.
    """
    all_movies = []
    all_sources = []

    # Extract from all PDFs
    pdf_files = list(PDF_DIR.glob('*.pdf'))
    print(f"Found {len(pdf_files)} PDF files\n")

    for pdf_path in pdf_files:
        movies, source = extract_movies_from_pdf(pdf_path)
        all_movies.extend(movies)
        all_sources.append(source)

    print(f"\nTotal movies extracted: {len(all_movies)}")

    # Enrich with OMDB (parallel)
    print(f"\nEnriching {len(all_movies)} movies with OMDB (using {max_workers} workers)...")

    enriched_movies = []
    enriched_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_movie = {
            executor.submit(enrich_movie, m): m for m in all_movies
        }

        for future in as_completed(future_to_movie):
            try:
                movie = future.result()
                enriched_movies.append(movie)
                if movie.enriched:
                    enriched_count += 1
            except Exception as e:
                original = future_to_movie[future]
                print(f"Error enriching '{original.title}': {e}")
                enriched_movies.append(original)

    print(f"Enrichment complete: {enriched_count}/{len(all_movies)} movies enriched")

    # Build catalog index
    categories = list(set(m.pdf_category for m in enriched_movies))

    catalog = CatalogIndex(
        movies=enriched_movies,
        sources=all_sources,
        categories=categories,
        total_count=len(enriched_movies),
        enriched_count=enriched_count
    )

    return catalog


def calculate_pdf_stats(movies: list[Movie]) -> list[dict]:
    """Calculate enrichment statistics per PDF source."""
    from collections import defaultdict

    stats = defaultdict(lambda: {'total': 0, 'enriched': 0})

    for movie in movies:
        source = movie.source_pdf
        stats[source]['total'] += 1
        if movie.enriched:
            stats[source]['enriched'] += 1

    # Convert to sorted list (by success rate, lowest first = most problematic)
    result = []
    for pdf, counts in sorted(stats.items(), key=lambda x: x[1]['enriched'] / max(x[1]['total'], 1)):
        result.append({
            'pdf_file': pdf,
            'total_movies': counts['total'],
            'enriched_movies': counts['enriched'],
            'success_rate': counts['enriched'] / max(counts['total'], 1),
            'failed_movies': counts['total'] - counts['enriched']
        })

    return result


def print_pdf_stats_table(pdf_stats: list[dict]) -> None:
    """Print a formatted table of per-PDF success rates."""
    print("\n" + "=" * 70)
    print("Per-PDF Enrichment Success Rates")
    print("=" * 70)
    print(f"{'PDF File':<35} {'Total':>8} {'Enriched':>10} {'Rate':>8} {'Status'}")
    print("-" * 70)

    for stat in pdf_stats:
        pdf_name = stat['pdf_file'][:34]
        total = stat['total_movies']
        enriched = stat['enriched_movies']
        rate = stat['success_rate']

        # Status indicator based on success rate
        if rate >= 0.5:
            status = "✓ Good"
        elif rate >= 0.3:
            status = "⚠ Fair"
        elif rate > 0:
            status = "✗ Poor"
        else:
            status = "✗ None"

        print(f"{pdf_name:<35} {total:>8} {enriched:>10} {rate:>7.1%} {status}")

    print("-" * 70)


def export_catalog(catalog: CatalogIndex, output_dir: Path) -> None:
    """
    Export catalog to all required formats.

    Args:
        catalog: The CatalogIndex to export.
        output_dir: Directory for output files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Calculate per-PDF statistics
    pdf_stats = calculate_pdf_stats(catalog.movies)

    # 1. JSON for ObservableJS (primary)
    json_path = output_dir / 'catalog.json'
    catalog.to_json(str(json_path))
    print(f"Exported JSON: {json_path}")

    # 2. CSV for backwards compatibility
    csv_path = output_dir / 'all_movies.csv'

    # Flatten movies for CSV
    csv_data = []
    for m in catalog.movies:
        row = m.model_dump()
        # Flatten genre list
        row['genre'] = ', '.join(row.get('genre', []))
        csv_data.append(row)

    df = pd.DataFrame(csv_data)
    df.to_csv(csv_path, index=False)
    print(f"Exported CSV: {csv_path}")

    # 3. Processing summary with per-PDF stats
    summary = {
        'total_movies': catalog.total_count,
        'enriched_movies': catalog.enriched_count,
        'enrichment_rate': catalog.enriched_count / max(catalog.total_count, 1),
        'categories': catalog.categories,
        'pdf_sources': [s.model_dump() for s in catalog.sources],
        'pdf_stats': pdf_stats  # NEW: Per-PDF success rates
    }

    summary_path = output_dir / 'processing_summary.json'
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Exported summary: {summary_path}")

    # 4. Per-PDF stats CSV for easy analysis
    stats_csv_path = output_dir / 'pdf_success_rates.csv'
    pd.DataFrame(pdf_stats).to_csv(stats_csv_path, index=False)
    print(f"Exported PDF stats: {stats_csv_path}")

    # Print table to console
    print_pdf_stats_table(pdf_stats)


def main():
    """Run the complete pipeline."""
    print("=" * 60)
    print("Movie Catalog Pipeline")
    print("=" * 60)

    # Check for OMDB API key
    if not os.getenv('OMDB_API_KEY'):
        print("\nWarning: OMDB_API_KEY not set. Enrichment will fail.")
        print("Set it in .env file or environment variables.\n")

    # Process all PDFs
    catalog = process_all_pdfs(max_workers=5)

    # Export results
    print("\n" + "=" * 60)
    print("Exporting results...")
    export_catalog(catalog, OUTPUT_DIR)

    print("\n" + "=" * 60)
    print("Pipeline complete!")
    print(f"Total movies: {catalog.total_count}")
    print(f"Enriched: {catalog.enriched_count}")
    print(f"Success rate: {catalog.enriched_count / max(catalog.total_count, 1):.1%}")


if __name__ == "__main__":
    import re
    main()
