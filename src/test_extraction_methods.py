#!/usr/bin/env python3
"""
Test script to compare two PDF extraction methods for CINE.pdf

Method 1: Regex-based extraction with PyPDF2 (line-by-line)
Method 2: Hybrid extraction (multi-line reconstruction)
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from pdf_extractor import extract_cine_regex, extract_cine_hybrid, compare_extraction_methods

PDF_PATH = Path(__file__).parent.parent / 'data' / 'pdfs' / 'CINE.pdf'


def main():
    print("=" * 70)
    print("PDF EXTRACTION METHODS COMPARISON")
    print("=" * 70)
    print(f"Testing on: {PDF_PATH}")
    print()

    # Run comparison
    metrics = compare_extraction_methods(str(PDF_PATH), sample_size=20)

    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    for method_name, data in metrics.items():
        print(f"\n{method_name.upper()} Method:")
        print(f"  Total entries: {data['total_entries']}")
        print(f"  With director: {data['with_director']} ({100*data['with_director']/max(data['total_entries'],1):.1f}%)")
        print(f"  With English title: {data['with_english_title']} ({100*data['with_english_title']/max(data['total_entries'],1):.1f}%)")

    # Show sample entries
    print("\n" + "=" * 70)
    print("SAMPLE ENTRIES (Method 1 - Regex)")
    print("=" * 70)
    for entry in metrics['regex']['sample'][:5]:
        print(f"\nID: {entry['id']}")
        print(f"  Spanish: {entry['title_spanish']}")
        print(f"  English: {entry['title_english'] or 'N/A'}")
        print(f"  Director: {entry['director'] or 'N/A'}")

    print("\n" + "=" * 70)
    print("SAMPLE ENTRIES (Method 2 - Hybrid)")
    print("=" * 70)
    for entry in metrics['hybrid']['sample'][:5]:
        print(f"\nID: {entry['id']}")
        print(f"  Spanish: {entry['title_spanish']}")
        print(f"  English: {entry['title_english'] or 'N/A'}")
        print(f"  Director: {entry['director'] or 'N/A'}")

    # Save results for manual inspection
    print("\n" + "=" * 70)
    print("SAVING RESULTS")
    print("=" * 70)

    output_dir = Path(__file__).parent.parent / 'data' / 'intermediate_results'
    output_dir.mkdir(parents=True, exist_ok=True)

    import pandas as pd

    # Re-run to get full dataframes
    df_regex = extract_cine_regex(str(PDF_PATH))
    df_hybrid = extract_cine_hybrid(str(PDF_PATH))

    regex_file = output_dir / 'cine_regex_method.csv'
    hybrid_file = output_dir / 'cine_hybrid_method.csv'

    df_regex.to_csv(regex_file, index=False)
    df_hybrid.to_csv(hybrid_file, index=False)

    print(f"Saved regex results to: {regex_file}")
    print(f"Saved hybrid results to: {hybrid_file}")

    print("\nDone! Compare CSV files to evaluate method accuracy.")


if __name__ == "__main__":
    main()
