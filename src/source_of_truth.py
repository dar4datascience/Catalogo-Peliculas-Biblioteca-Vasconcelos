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

def update_movie(
    raw_title: str,
    omdb_data: Dict[str, Any],
    match_type: str = "manual_confirmation",
    catalogue: str = "CINE.pdf",
    catalogue_id: Optional[int] = None,
    page_number: Optional[int] = None,
) -> bool:
    """Update or add a movie to the Source of Truth."""
    sot = load_sot()
    entry: Dict[str, Any] = {
        "imdb_id": omdb_data.get("imdbID"),
        "matched_title": omdb_data.get("Title"),
        "match_type": match_type,
        "catalogue": catalogue,
        "full_data": omdb_data,
    }
    if catalogue_id is not None:
        entry["catalogue_id"] = catalogue_id
    if page_number is not None:
        entry["page_number"] = page_number
    # Preserve existing catalogue metadata if not provided
    existing = sot.get(raw_title, {})
    if catalogue_id is None and "catalogue_id" in existing:
        entry["catalogue_id"] = existing["catalogue_id"]
    if page_number is None and "page_number" in existing:
        entry["page_number"] = existing["page_number"]
    if not entry.get("catalogue") and "catalogue" in existing:
        entry["catalogue"] = existing["catalogue"]
    sot[raw_title] = entry
    return save_sot(sot)

def get_all_mappings() -> Dict[str, Any]:
    """Get all raw title to metadata mappings."""
    return load_sot()
