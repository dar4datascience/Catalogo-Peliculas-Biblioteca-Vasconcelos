"""
Re-process failed movie enrichments using LLM-assisted matching.
Can be run after initial pipeline to improve success rates.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from models import Movie
from llm_enrichment import enhanced_enrich_movie, TitleAnalyzer
from pipeline import export_catalog, OUTPUT_DIR

load_dotenv()

CATALOG_PATH = Path(__file__).parent.parent / 'data' / 'final_results' / 'catalog.json'


def load_catalog() -> tuple[list[Movie], list[Movie]]:
    """Load catalog and split into enriched/failed."""
    with open(CATALOG_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    all_movies = []
    for m in data.get('movies', []):
        movie = Movie(**m)
        all_movies.append(movie)
    
    enriched = [m for m in all_movies if m.enriched]
    failed = [m for m in all_movies if not m.enriched]
    
    return enriched, failed


def reprocess_failed_movies(failed_movies: list[Movie], max_workers: int = 3) -> list[Movie]:
    """Re-process failed movies with LLM-enhanced enrichment."""
    print(f"\nRe-processing {len(failed_movies)} failed movies with LLM enhancement...")
    print(f"Using {max_workers} parallel workers\n")
    
    newly_enriched = []
    still_failed = []
    
    def process_one(movie: Movie) -> Movie:
        """Process a single movie."""
        return enhanced_enrich_movie(movie)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_movie = {executor.submit(process_one, m): m for m in failed_movies}
        
        for i, future in enumerate(as_completed(future_to_movie)):
            try:
                movie = future.result()
                if movie.enriched:
                    newly_enriched.append(movie)
                    print(f"  ✓ [{i+1}/{len(failed_movies)}] '{movie.title}' → '{movie.matched_title}'")
                else:
                    still_failed.append(movie)
                    analysis = TitleAnalyzer.normalize_title(movie.title, movie.pdf_category)
                    print(f"  ✗ [{i+1}/{len(failed_movies)}] '{movie.title}' (tried: {analysis['variations']})")
            except Exception as e:
                original = future_to_movie[future]
                print(f"  ! [{i+1}/{len(failed_movies)}] Error processing '{original.title}': {e}")
                still_failed.append(original)
    
    return newly_enriched, still_failed


def analyze_improvement(original_enriched: list, new_enriched: list, still_failed: list) -> dict:
    """Analyze the improvement from reprocessing."""
    total = len(original_enriched) + len(new_enriched) + len(still_failed)
    
    stats = {
        'original_enriched': len(original_enriched),
        'newly_enriched': len(new_enriched),
        'still_failed': len(still_failed),
        'total_movies': total,
        'original_success_rate': len(original_enriched) / total,
        'new_success_rate': (len(original_enriched) + len(new_enriched)) / total,
        'improvement': len(new_enriched) / total,
        'improvement_percentage': (len(new_enriched) / (total - len(original_enriched))) * 100
    }
    
    return stats


def save_llm_prompts_for_manual_review(failed_movies: list, output_path: Path):
    """Generate LLM prompts for movies that still failed."""
    from llm_enrichment import generate_llm_prompt_for_failed
    
    prompts = []
    for movie in failed_movies:
        analysis = TitleAnalyzer.normalize_title(movie.title, movie.pdf_category)
        prompt = generate_llm_prompt_for_failed(
            movie.title,
            analysis,
            context=f"PDF Category: {movie.pdf_category}"
        )
        prompts.append({
            'title': movie.title,
            'source_pdf': movie.source_pdf,
            'category': movie.pdf_category,
            'llm_prompt': prompt
        })
    
    output_path.write_text(
        json.dumps(prompts, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    print(f"\nGenerated LLM prompts for manual review: {output_path}")


def main():
    """Main reprocessing workflow."""
    print("=" * 70)
    print("LLM-Enhanced Movie Reprocessing")
    print("=" * 70)
    
    # Load existing catalog
    if not CATALOG_PATH.exists():
        print(f"\nError: Catalog not found at {CATALOG_PATH}")
        print("Run the main pipeline first: python src/pipeline.py")
        return
    
    enriched, failed = load_catalog()
    
    print(f"\nCatalog Status:")
    print(f"  Already enriched: {len(enriched)}")
    print(f"  Failed matches:   {len(failed)}")
    print(f"  Total:            {len(enriched) + len(failed)}")
    print(f"  Current rate:     {len(enriched) / (len(enriched) + len(failed)):.1%}")
    
    if not failed:
        print("\n✓ No failed movies to reprocess!")
        return
    
    # Reprocess failed movies
    newly_enriched, still_failed = reprocess_failed_movies(failed, max_workers=3)
    
    # Analyze improvement
    stats = analyze_improvement(enriched, newly_enriched, still_failed)
    
    print("\n" + "=" * 70)
    print("Reprocessing Results")
    print("=" * 70)
    print(f"  Newly enriched:          {stats['newly_enriched']}")
    print(f"  Still failed:            {stats['still_failed']}")
    print(f"  New success rate:        {stats['new_success_rate']:.1%}")
    print(f"  Improvement:             +{stats['improvement']:.1%} ({stats['improvement_percentage']:.1f}% of failed)")
    
    # Merge and save
    all_movies = enriched + newly_enriched + still_failed
    
    # Build new catalog
    from models import CatalogIndex, PDFSource
    
    # Load original sources
    with open(CATALOG_PATH, 'r', encoding='utf-8') as f:
        old_data = json.load(f)
    
    sources = [PDFSource(**s) for s in old_data.get('sources', [])]
    categories = list(set(m.pdf_category for m in all_movies))
    
    new_catalog = CatalogIndex(
        movies=all_movies,
        sources=sources,
        categories=categories,
        total_count=len(all_movies),
        enriched_count=len([m for m in all_movies if m.enriched])
    )
    
    # Export
    print("\n" + "=" * 70)
    print("Exporting updated catalog...")
    print("=" * 70)
    export_catalog(new_catalog, OUTPUT_DIR)
    
    # Save LLM prompts for remaining failures
    if still_failed:
        prompts_path = OUTPUT_DIR / 'manual_review_prompts.json'
        save_llm_prompts_for_manual_review(still_failed, prompts_path)
        print(f"\n{len(still_failed)} movies still need manual review.")
        print(f"LLM prompts saved to: {prompts_path}")
    
    print("\n" + "=" * 70)
    print("Reprocessing complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
