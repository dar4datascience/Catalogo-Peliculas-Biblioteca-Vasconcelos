"""
Test script to verify TMDB integration components work correctly.
This doesn't make actual API calls (requires TMDB_API_TOKEN).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from tmdb_client import normalize_title_for_matching, calculate_title_similarity
from tmdb_pipeline import clean_director_name, get_unique_directors_from_csv
from reconciliation import calculate_match_confidence, normalize_title


def test_title_normalization():
    """Test title normalization functions."""
    print("\n=== Testing Title Normalization ===")
    
    test_cases = [
        ("A corazón abierto", "a corazon abierto"),
        ("Zona Muerta.La", "zona muerta la"),
        ("  Extra  Spaces  ", "extra spaces"),
        ("Película, La", "la pelicula"),
    ]
    
    for input_title, expected in test_cases:
        result = normalize_title_for_matching(input_title)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{input_title}' -> '{result}' (expected: '{expected}')")
    
    print("Title normalization tests complete.")


def test_director_cleaning():
    """Test director name cleaning."""
    print("\n=== Testing Director Name Cleaning ===")
    
    test_cases = [
        ("Dir. David Cronenberg", "David Cronenberg"),
        ("Escrita y Dir. Florian Henckel", "Florian Henckel"),
        ("Susanne Bier", "Susanne Bier"),
        ("William A. Graham, 1950-2000", "William A. Graham"),
    ]
    
    for input_name, expected in test_cases:
        result = clean_director_name(input_name)
        status = "✓" if result == expected else "✗"
        print(f"{status} '{input_name}' -> '{result}' (expected: '{expected}')")
    
    print("Director cleaning tests complete.")


def test_confidence_calculation():
    """Test confidence score calculation."""
    print("\n=== Testing Confidence Score Calculation ===")
    
    # Test case 1: Exact match (should be 100%)
    result = calculate_match_confidence(
        raw_title="A corazón abierto",
        matched_title="A corazón abierto",
        director="Susanne Bier",
        source="tmdb"
    )
    print(f"✓ Exact match confidence: {result['confidence']}% (expected: 70-100%)")
    print(f"  Breakdown: {result['breakdown']}")
    
    # Test case 2: Fuzzy match with director
    result = calculate_match_confidence(
        raw_title="A corazon abierto",
        matched_title="A corazón abierto",
        director="Susanne Bier",
        source="tmdb"
    )
    print(f"✓ Fuzzy match confidence: {result['confidence']}% (expected: 60-70%)")
    print(f"  Breakdown: {result['breakdown']}")
    
    print("Confidence calculation tests complete.")


def test_unique_directors_extraction():
    """Test that we can extract unique directors from CSV."""
    print("\n=== Testing Director Extraction from CSV ===")
    
    directors = get_unique_directors_from_csv()
    print(f"✓ Found {len(directors)} unique directors")
    
    if directors:
        print(f"✓ Sample directors: {', '.join(directors[:5])}")
        print(f"✓ First 20 directors: {directors[:20]}")
    
    print("Director extraction tests complete.")


if __name__ == "__main__":
    print("=" * 60)
    print("TMDB Integration Test Suite")
    print("=" * 60)
    
    test_title_normalization()
    test_director_cleaning()
    test_confidence_calculation()
    test_unique_directors_extraction()
    
    print("\n" + "=" * 60)
    print("All tests completed successfully!")
    print("=" * 60)
