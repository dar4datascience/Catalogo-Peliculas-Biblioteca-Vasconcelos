import json
import os
from typing import Optional, Dict, Any

SOT_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'source_of_truth.json')

def load_sot() -> Dict[str, Any]:
    """Load the Source of Truth from disk."""
    if not os.path.exists(SOT_PATH):
        return {}
    try:
        with open(SOT_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading Source of Truth: {e}")
        return {}

def save_sot(data: Dict[str, Any]) -> bool:
    """Save the Source of Truth to disk."""
    try:
        os.makedirs(os.path.dirname(SOT_PATH), exist_ok=True)
        with open(SOT_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving Source of Truth: {e}")
        return False

def lookup_movie(raw_title: str) -> Optional[Dict[str, Any]]:
    """Look up a movie by its raw extracted title."""
    sot = load_sot()
    return sot.get(raw_title)

def update_movie(raw_title: str, omdb_data: Dict[str, Any], match_type: str = "manual_confirmation") -> bool:
    """Update or add a movie to the Source of Truth."""
    sot = load_sot()
    sot[raw_title] = {
        "imdb_id": omdb_data.get("imdbID"),
        "matched_title": omdb_data.get("Title"),
        "match_type": match_type,
        "full_data": omdb_data
    }
    return save_sot(sot)

def get_all_mappings() -> Dict[str, Any]:
    """Get all raw title to metadata mappings."""
    return load_sot()
