"""
DuckDB-based hybrid scorer for OMDB candidate disambiguation.

OMDB has no filmography endpoint, so candidates arrive as a list of dicts
already fetched from the OMDB &s= search API.  This module re-scores those
candidates using:
  - jaro_winkler_similarity (DuckDB built-in, weight 0.4)
  - array_cosine_distance   (DuckDB VSS, weight 0.4)
  - director match bonus    (normalised to weight 0.2)

An in-memory DuckDB connection is used — no persistence needed since candidate
lists are small (< 30 items) and ephemeral.

The scorer is triggered only when multiple candidates need disambiguation.
Single-result cases should bypass this entirely (handled by the caller).
"""

from __future__ import annotations

import sys
import os
from typing import List, Dict

import duckdb

sys.path.insert(0, os.path.dirname(__file__))
from embeddings import embed, EMBEDDING_DIM


class OMDBDuckDBScorer:
    """
    Stateless, in-memory DuckDB scorer for OMDB candidate lists.

    Typical usage:
        scorer = OMDBDuckDBScorer()
        ranked = scorer.score_candidates(query_title, candidates)
    """

    def score_candidates(
        self,
        query_title: str,
        candidates: List[Dict],
        min_score: int = 60,
    ) -> List[Dict]:
        """
        Re-score and re-rank a list of OMDB candidate dicts using hybrid similarity.

        Args:
            query_title: The catalog title being searched (Spanish or bilingual).
            candidates: List of dicts from search_director_filmography, each must have:
                        'title', 'imdbID', 'year', 'director', 'director_matched',
                        'title_score' (original thefuzz score).
            min_score:  Minimum hybrid score (0-100) to include in output.

        Returns:
            Candidates sorted by hybrid_score descending, each enriched with:
                'score'         – hybrid score 0-100 (replaces original thefuzz score)
                'hybrid_score'  – raw float 0-1
                'score_breakdown' – dict with individual signal scores
        """
        if not candidates:
            return []

        # Collect all texts to embed in one batch: query + all candidate titles
        candidate_titles = [c.get("title", "") for c in candidates]
        all_texts = [query_title] + candidate_titles
        all_embeddings = embed(all_texts)

        if not all_embeddings or len(all_embeddings) < len(all_texts):
            # Embedding failed — fall back to returning candidates unchanged
            return candidates

        query_emb = all_embeddings[0]
        cand_embeddings = all_embeddings[1:]

        # Build an in-memory DuckDB table for vectorised scoring
        conn = duckdb.connect(":memory:")
        conn.execute("INSTALL vss")
        conn.execute("LOAD vss")

        conn.execute(f"""
            CREATE TABLE candidates (
                idx         INTEGER,
                title       VARCHAR,
                imdb_id     VARCHAR,
                dir_matched BOOLEAN,
                title_emb   FLOAT[{EMBEDDING_DIM}]
            )
        """)

        for i, (cand, emb) in enumerate(zip(candidates, cand_embeddings)):
            conn.execute(
                "INSERT INTO candidates VALUES (?, ?, ?, ?, ?)",
                [
                    i,
                    cand.get("title", ""),
                    cand.get("imdbID", ""),
                    bool(cand.get("director_matched", False)),
                    emb,
                ],
            )

        # Score in one SQL pass
        rows = conn.execute(f"""
            SELECT
                idx,
                jaro_winkler_similarity(lower(?), lower(title))           AS jaro,
                array_cosine_distance(title_emb, ?::FLOAT[{EMBEDDING_DIM}]) AS cosine_dist,
                dir_matched
            FROM candidates
        """, [query_title, query_emb]).fetchall()

        conn.close()

        scored: List[Dict] = []
        for idx, jaro, cosine_dist, dir_matched in rows:
            cosine_sim = max(0.0, 1.0 - float(cosine_dist)) if cosine_dist is not None else jaro
            dir_bonus = 1.0 if dir_matched else 0.0

            hybrid = 0.4 * jaro + 0.4 * cosine_sim + 0.2 * dir_bonus
            hybrid_score_100 = min(int(hybrid * 100), 100)

            if hybrid_score_100 < min_score:
                continue

            enriched = dict(candidates[idx])
            enriched["score"] = hybrid_score_100
            enriched["hybrid_score"] = round(hybrid, 4)
            enriched["score_breakdown"] = {
                "jaro_winkler": round(jaro, 4),
                "cosine_similarity": round(cosine_sim, 4),
                "director_bonus": dir_bonus,
            }
            scored.append(enriched)

        scored.sort(key=lambda x: x["hybrid_score"], reverse=True)
        return scored
