"""
DuckDB-based storage and querying for TMDB director filmographies.
Uses DuckDB's built-in similarity functions for efficient matching.
"""

import os
import sys
import json
import duckdb
from pathlib import Path
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(__file__))
from tmdb_client import search_person, get_person_movie_credits

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
FINAL_DIR = DATA_DIR / "final_results"
DUCKDB_FILE = FINAL_DIR / "tmdb_directors.duckdb"


class TMDBDuckDB:
    """DuckDB-based storage for TMDB director filmographies."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DUCKDB_FILE)
        self.conn = duckdb.connect(self.db_path)
        self._init_tables()
    
    def _init_tables(self):
        """Initialize database tables."""
        # Directors table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS directors (
                id INTEGER PRIMARY KEY,
                name VARCHAR,
                tmdb_person_id INTEGER,
                popularity DOUBLE,
                movie_count INTEGER
            )
        """)
        
        # Movies/Filmography table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS filmography (
                movie_id INTEGER,
                director_id INTEGER,
                title VARCHAR,
                original_title VARCHAR,
                release_date DATE,
                release_year INTEGER,
                job VARCHAR,
                department VARCHAR,
                popularity DOUBLE,
                vote_average DOUBLE,
                vote_count INTEGER,
                PRIMARY KEY (movie_id, director_id),
                FOREIGN KEY (director_id) REFERENCES directors(id)
            )
        """)
        
        # Matches table for results
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                catalog_title VARCHAR,
                catalog_director VARCHAR,
                matched_movie_id INTEGER,
                matched_title VARCHAR,
                matched_original_title VARCHAR,
                jaro_winkler_score DOUBLE,
                levenshtein_distance INTEGER,
                confidence_score DOUBLE,
                match_type VARCHAR,
                source VARCHAR
            )
        """)
        
        # Create indexes for faster similarity searches
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_filmography_title ON filmography(title)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_filmography_original ON filmography(original_title)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_filmography_director ON filmography(director_id)")
    
    def add_director(self, name: str, tmdb_data: Dict) -> int:
        """Add a director and their filmography to the database."""
        # Check if director already exists
        result = self.conn.execute(
            "SELECT id FROM directors WHERE name = ?",
            [name]
        ).fetchone()
        
        if result:
            director_id = result[0]
        else:
            # Get next ID
            max_id = self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM directors").fetchone()[0]
            director_id = max_id + 1
            
            # Insert director
            self.conn.execute("""
                INSERT INTO directors (id, name, tmdb_person_id, popularity, movie_count)
                VALUES (?, ?, ?, ?, ?)
            """, [
                director_id,
                name,
                tmdb_data.get("tmdb_person_id"),
                tmdb_data.get("popularity"),
                tmdb_data.get("movie_count")
            ])
        
        # Insert filmography
        for movie in tmdb_data.get("filmography", []):
            release_date = movie.get("release_date")
            release_year = None
            if release_date and len(release_date) >= 4:
                try:
                    release_year = int(release_date[:4])
                except:
                    pass
            
            self.conn.execute("""
                INSERT OR REPLACE INTO filmography 
                (movie_id, director_id, title, original_title, release_date, release_year,
                 job, department, popularity, vote_average, vote_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                movie.get("id"),
                director_id,
                movie.get("title"),
                movie.get("original_title"),
                release_date if release_date else None,
                release_year,
                movie.get("job"),
                movie.get("department"),
                movie.get("popularity"),
                movie.get("vote_average"),
                movie.get("vote_count")
            ])
        
        return director_id
    
    def find_best_match(
        self,
        catalog_title: str,
        director_name: str,
        min_similarity: float = 0.6
    ) -> Optional[Dict]:
        """
        Find the best matching movie in a director's filmography using DuckDB's similarity functions.
        
        Uses jaro_winkler_similarity for fuzzy matching (good for name variations).
        """
        # Get director ID
        director_result = self.conn.execute(
            "SELECT id FROM directors WHERE name = ?",
            [director_name]
        ).fetchone()
        
        if not director_result:
            return None
        
        director_id = director_result[0]
        
        # Use DuckDB's similarity functions
        query = """
            SELECT 
                movie_id,
                title,
                original_title,
                release_year,
                jaro_winkler_similarity(lower(?), lower(title)) as jaro_title,
                jaro_winkler_similarity(lower(?), lower(original_title)) as jaro_original,
                levenshtein(lower(?), lower(title)) as lev_title,
                levenshtein(lower(?), lower(original_title)) as lev_original
            FROM filmography
            WHERE director_id = ?
            ORDER BY GREATEST(jaro_title, jaro_original) DESC
            LIMIT 1
        """
        
        result = self.conn.execute(query, [
            catalog_title, catalog_title,
            catalog_title, catalog_title,
            director_id
        ]).fetchone()
        
        if not result:
            return None
        
        movie_id, title, original_title, year, jaro_title, jaro_original, lev_title, lev_original = result
        best_jaro = max(jaro_title or 0, jaro_original or 0)
        
        if best_jaro < min_similarity:
            return None
        
        return {
            "movie_id": movie_id,
            "title": title,
            "original_title": original_title,
            "year": year,
            "jaro_winkler_score": best_jaro,
            "levenshtein_distance": min(lev_title or 999, lev_original or 999),
            "matched_on": "original_title" if jaro_original > jaro_title else "title"
        }
    
    def batch_find_matches(
        self,
        catalog_entries: List[Dict],
        min_similarity: float = 0.6
    ) -> List[Dict]:
        """
        Batch match multiple catalog entries against their directors' filmographies.
        
        Args:
            catalog_entries: List of dicts with 'title' and 'director'
            min_similarity: Minimum Jaro-Winkler similarity threshold
        """
        results = []
        
        for entry in catalog_entries:
            title = entry.get("title", "")
            director = entry.get("director", "")
            
            match = self.find_best_match(title, director, min_similarity)
            
            if match:
                # Calculate confidence score
                confidence = self._calculate_confidence(
                    catalog_title=title,
                    match=match
                )
                
                results.append({
                    "catalog_title": title,
                    "director": director,
                    "matched": True,
                    **match,
                    **confidence
                })
            else:
                results.append({
                    "catalog_title": title,
                    "director": director,
                    "matched": False
                })
        
        return results
    
    def _calculate_confidence(self, catalog_title: str, match: Dict) -> Dict:
        """
        Calculate confidence score based on similarity metrics.
        
        Confidence formula adapted for DuckDB metrics:
        - Jaro-Winkler >= 0.9: exact match equivalent (40 points)
        - Jaro-Winkler 0.7-0.9: high fuzzy (30-40 points scaled)
        - Jaro-Winkler < 0.7: low confidence
        - Director confirmed: 30 points
        """
        jaro_score = match.get("jaro_winkler_score", 0)
        
        # Scale Jaro-Winkler (0-1) to 0-40 points
        if jaro_score >= 0.9:
            title_points = 40
        elif jaro_score >= 0.7:
            title_points = int(30 + (jaro_score - 0.7) * 50)  # 30-40 range
        else:
            title_points = int(jaro_score * 42)  # 0-30 range
        
        # Director is confirmed (we searched their filmography)
        director_points = 30
        
        total = min(title_points + director_points, 100)
        
        return {
            "confidence": total,
            "confidence_breakdown": {
                "title_similarity": title_points,
                "director_confirmed": director_points
            },
            "match_type": "exact" if jaro_score >= 0.9 else ("high_fuzzy" if jaro_score >= 0.8 else "fuzzy")
        }
    
    def load_from_json_cache(self, cache_file: str = None):
        """Load directors from the existing JSON cache into DuckDB."""
        cache_file = cache_file or (FINAL_DIR / "director_filmographies.json")
        
        if not os.path.exists(cache_file):
            print(f"Cache file not found: {cache_file}")
            return 0
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        
        count = 0
        for director_name, data in cache.items():
            self.add_director(director_name, data)
            count += 1
        
        print(f"Loaded {count} directors into DuckDB")
        return count
    
    def get_stats(self) -> Dict:
        """Get database statistics."""
        director_count = self.conn.execute(
            "SELECT COUNT(*) FROM directors"
        ).fetchone()[0]
        
        movie_count = self.conn.execute(
            "SELECT COUNT(*) FROM filmography"
        ).fetchone()[0]
        
        match_count = self.conn.execute(
            "SELECT COUNT(*) FROM matches"
        ).fetchone()[0]
        
        return {
            "directors": director_count,
            "movies": movie_count,
            "matches": match_count
        }
    
    def query_similarity_distribution(self) -> List[Dict]:
        """Get distribution of similarity scores for all matches."""
        result = self.conn.execute("""
            SELECT 
                CASE 
                    WHEN jaro_winkler_score >= 0.9 THEN '90-100% (excellent)'
                    WHEN jaro_winkler_score >= 0.8 THEN '80-89% (high)'
                    WHEN jaro_winkler_score >= 0.7 THEN '70-79% (medium)'
                    WHEN jaro_winkler_score >= 0.6 THEN '60-69% (low)'
                    ELSE 'Below 60% (poor)'
                END as bucket,
                COUNT(*) as count,
                AVG(confidence_score) as avg_confidence
            FROM matches
            GROUP BY bucket
            ORDER BY avg_confidence DESC
        """).fetchall()
        
        return [
            {"bucket": row[0], "count": row[1], "avg_confidence": row[2]}
            for row in result
        ]
    
    def close(self):
        """Close database connection."""
        self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def build_duckdb_from_cache():
    """Build DuckDB database from existing JSON cache."""
    with TMDBDuckDB() as db:
        count = db.load_from_json_cache()
        stats = db.get_stats()
        print(f"\nDuckDB stats: {stats}")
    return count


if __name__ == "__main__":
    # Build the database from existing cache
    build_duckdb_from_cache()
    
    # Test with a sample query
    with TMDBDuckDB() as db:
        # Test match
        result = db.find_best_match(
            catalog_title="A corazón abierto",
            director_name="Susanne Bier"
        )
        if result:
            print(f"\nTest match result: {json.dumps(result, indent=2, ensure_ascii=False)}")
