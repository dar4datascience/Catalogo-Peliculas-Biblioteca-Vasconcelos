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
from embeddings import embed, embed_one, EMBEDDING_DIM

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
FINAL_DIR = DATA_DIR / "final_results"
DUCKDB_FILE = FINAL_DIR / "tmdb_directors.duckdb"


class TMDBDuckDB:
    """DuckDB-based storage for TMDB director filmographies."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DUCKDB_FILE)
        self.conn = duckdb.connect(self.db_path)
        self._load_extensions()
        self._init_tables()
    
    def _load_extensions(self):
        """Install and load DuckDB FTS and VSS extensions."""
        self.conn.execute("INSTALL fts")
        self.conn.execute("LOAD fts")
        self.conn.execute("INSTALL vss")
        self.conn.execute("LOAD vss")
        self.conn.execute("SET hnsw_enable_experimental_persistence = true")

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
                title_embedding FLOAT[384],
                PRIMARY KEY (movie_id, director_id),
                FOREIGN KEY (director_id) REFERENCES directors(id)
            )
        """)
        # Migration: add title_embedding column to pre-existing databases
        try:
            self.conn.execute(f"ALTER TABLE filmography ADD COLUMN title_embedding FLOAT[{EMBEDDING_DIM}]")
        except Exception:
            pass  # Column already exists
        
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
        movies = tmdb_data.get("filmography", [])

        # Batch-embed all titles at once to avoid per-row model calls
        embed_texts = [
            f"{m.get('title', '')} {m.get('original_title', '')}".strip()
            for m in movies
        ]
        embeddings = embed(embed_texts) if embed_texts else []

        for idx, movie in enumerate(movies):
            release_date = movie.get("release_date")
            release_year = None
            if release_date and len(release_date) >= 4:
                try:
                    release_year = int(release_date[:4])
                except Exception:
                    pass

            title_emb = embeddings[idx] if idx < len(embeddings) else None

            self.conn.execute("""
                INSERT OR REPLACE INTO filmography 
                (movie_id, director_id, title, original_title, release_date, release_year,
                 job, department, popularity, vote_average, vote_count, title_embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                movie.get("vote_count"),
                title_emb,
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
    
    def build_fts_index(self):
        """Build a BM25 full-text search index over filmography titles."""
        self.conn.execute("""
            PRAGMA create_fts_index(
                'filmography', 'movie_id', 'title', 'original_title',
                stemmer = 'porter',
                lower = 1,
                overwrite = 1
            )
        """)
        print("FTS index built on filmography.")

    def build_hnsw_index(self):
        """Build an HNSW cosine index over title_embedding for fast VSS."""
        # Drop first if it exists (overwrite-safe)
        try:
            self.conn.execute("DROP INDEX IF EXISTS filmography_hnsw")
        except Exception:
            pass
        self.conn.execute("""
            CREATE INDEX filmography_hnsw
            ON filmography USING HNSW (title_embedding)
            WITH (metric = 'cosine')
        """)
        print("HNSW index built on filmography.title_embedding.")

    def find_best_match_hybrid(
        self,
        catalog_title: str,
        director_name: str,
        min_similarity: float = 0.55,
    ) -> Optional[Dict]:
        """
        Find the best matching movie using a hybrid score:
          hybrid = 0.4 * jaro_winkler + 0.2 * bm25_norm + 0.4 * cosine_similarity

        Falls back to Jaro-Winkler-only when the embedding is NULL
        (pre-existing rows without embeddings).
        """
        director_result = self.conn.execute(
            "SELECT id FROM directors WHERE name = ?",
            [director_name]
        ).fetchone()

        if not director_result:
            return None

        director_id = director_result[0]

        # Embed the query title once
        query_emb = embed_one(catalog_title)
        if not query_emb:
            # Graceful fallback to Jaro-Winkler only
            return self.find_best_match(catalog_title, director_name, min_similarity)

        # BM25 scores for all films by this director
        try:
            bm25_rows = self.conn.execute("""
                SELECT
                    movie_id,
                    fts_main_filmography.match_bm25(movie_id, ?) AS bm25_raw
                FROM filmography
                WHERE director_id = ?
            """, [catalog_title, director_id]).fetchall()
            bm25_map = {row[0]: (row[1] or 0.0) for row in bm25_rows}
            max_bm25 = max(bm25_map.values()) if bm25_map else 0.0
        except Exception:
            bm25_map = {}
            max_bm25 = 0.0

        # Pull all candidates with Jaro + cosine in one SQL pass
        rows = self.conn.execute("""
            SELECT
                movie_id,
                title,
                original_title,
                release_year,
                jaro_winkler_similarity(lower(?), lower(title))       AS jaro_title,
                jaro_winkler_similarity(lower(?), lower(original_title)) AS jaro_original,
                levenshtein(lower(?), lower(title))                   AS lev_title,
                levenshtein(lower(?), lower(original_title))          AS lev_original,
                CASE
                    WHEN title_embedding IS NOT NULL
                    THEN array_cosine_distance(title_embedding, ?::FLOAT[384])
                    ELSE NULL
                END AS cosine_dist
            FROM filmography
            WHERE director_id = ?
        """, [
            catalog_title, catalog_title,
            catalog_title, catalog_title,
            query_emb,
            director_id,
        ]).fetchall()

        if not rows:
            return None

        best_hybrid = 0.0
        best_row = None

        for row in rows:
            movie_id, title, original_title, year, jaro_t, jaro_o, lev_t, lev_o, cosine_dist = row

            jaro = max(jaro_t or 0.0, jaro_o or 0.0)

            # Normalise BM25 to [0, 1]
            raw_bm25 = bm25_map.get(movie_id, 0.0)
            bm25_norm = (raw_bm25 / max_bm25) if max_bm25 > 0 else 0.0

            # Cosine distance → similarity (NULL-safe, distance in [0,2])
            if cosine_dist is not None:
                cosine_sim = max(0.0, 1.0 - float(cosine_dist))
            else:
                cosine_sim = jaro  # fallback: mirror Jaro

            hybrid = 0.4 * jaro + 0.2 * bm25_norm + 0.4 * cosine_sim

            if hybrid > best_hybrid:
                best_hybrid = hybrid
                best_row = {
                    "movie_id": movie_id,
                    "title": title,
                    "original_title": original_title,
                    "year": year,
                    "jaro_winkler_score": jaro,
                    "bm25_score": bm25_norm,
                    "cosine_similarity": cosine_sim,
                    "hybrid_score": hybrid,
                    "levenshtein_distance": min(lev_t or 999, lev_o or 999),
                    "matched_on": "original_title" if (jaro_o or 0) > (jaro_t or 0) else "title",
                }

        if best_row is None or best_hybrid < min_similarity:
            return None

        return best_row

    def _calculate_confidence(self, catalog_title: str, match: Dict) -> Dict:
        """
        Calculate confidence score based on similarity metrics.

        Supports both legacy (Jaro-only) and hybrid matches.
        Confidence formula:
        - Hybrid score >= 0.9: exact match equivalent (40 points)
        - Hybrid score 0.7-0.9: high fuzzy (30-40 points scaled)
        - Hybrid score < 0.7: low confidence
        - Director confirmed: 30 points
        """
        hybrid_score = match.get("hybrid_score")
        jaro_score = match.get("jaro_winkler_score", 0)
        primary_score = hybrid_score if hybrid_score is not None else jaro_score

        # Scale primary score (0-1) to 0-40 points
        if primary_score >= 0.9:
            title_points = 40
        elif primary_score >= 0.7:
            title_points = int(30 + (primary_score - 0.7) * 50)  # 30-40 range
        else:
            title_points = int(primary_score * 42)  # 0-30 range

        # Director is confirmed (we searched their filmography)
        director_points = 30

        total = min(title_points + director_points, 100)

        breakdown = {
            "title_similarity": title_points,
            "director_confirmed": director_points,
        }
        if hybrid_score is not None:
            breakdown["hybrid_similarity"] = round(hybrid_score, 4)
            breakdown["jaro_winkler"] = round(jaro_score, 4)
            breakdown["bm25_norm"] = round(match.get("bm25_score", 0.0), 4)
            breakdown["cosine_similarity"] = round(match.get("cosine_similarity", 0.0), 4)

        return {
            "confidence": total,
            "confidence_breakdown": breakdown,
            "match_type": "exact" if primary_score >= 0.9 else ("high_fuzzy" if primary_score >= 0.8 else "fuzzy"),
        }
    
    def load_from_json_cache(self, cache_file: str = None, build_indexes: bool = True):
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

        if build_indexes and count > 0:
            print("Building FTS and HNSW indexes...")
            self.build_fts_index()
            self.build_hnsw_index()

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
