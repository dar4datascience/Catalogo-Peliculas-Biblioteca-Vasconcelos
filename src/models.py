"""
Pydantic models for the movie catalog data pipeline.
Provides type-safe data structures for movies, enrichment, and PDF sources.
"""

from typing import Optional
from pydantic import BaseModel, Field


class PDFSource(BaseModel):
    """Source PDF metadata."""
    file_name: str
    category: str  # BLU-RAY, CINE, INFANTILES, etc.
    page_count: int
    has_index: bool = False
    index_entries: list[dict] = Field(default_factory=list)


class Movie(BaseModel):
    """Movie data model with enrichment support."""
    # Core identification
    title: str
    original_title: Optional[str] = None
    source_pdf: str
    pdf_category: str  # Derived from PDF filename

    # OMDB enrichment data (all optional)
    imdb_id: Optional[str] = None
    year: Optional[str] = None
    director: Optional[str] = None
    writer: Optional[str] = None
    actors: Optional[str] = None
    plot: Optional[str] = None
    language: Optional[str] = None
    country: Optional[str] = None
    awards: Optional[str] = None
    poster: Optional[str] = None
    genre: list[str] = Field(default_factory=list)

    # Ratings
    imdb_rating: Optional[str] = None
    imdb_votes: Optional[str] = None
    metascore: Optional[str] = None

    # OMDB match metadata
    enriched: bool = False
    match_type: Optional[str] = None  # 'exact', 'fuzzy', 'english_fallback', etc.
    searched_title: Optional[str] = None
    matched_title: Optional[str] = None

    # PDF navigation (Phase 5)
    pdf_page: Optional[int] = None

    class Config:
        extra = "allow"  # Allow additional fields from OMDB

    def to_observable_dict(self) -> dict:
        """Convert to dict optimized for ObservableJS consumption."""
        data = self.model_dump()

        # Add computed fields for frontend filtering
        data['search_text'] = ' '.join(filter(None, [
            self.title,
            self.original_title or '',
            self.director or '',
            self.plot or '',
            ' '.join(self.genre),
            self.country or ''
        ])).lower()

        # Decade for filtering
        if self.year and self.year.isdigit():
            year_int = int(self.year)
            data['decade'] = (year_int // 10) * 10
        else:
            data['decade'] = None

        # Ensure poster has fallback
        if not self.poster or self.poster == 'N/A':
            data['poster'] = 'https://i.imgur.com/Ngnm5v6.png'

        # Normalize category for display
        category_map = {
            'BLU- RAY': 'Blu-ray',
            'BLU-RAY': 'Blu-ray',
            'CINE': 'Cine',
            'PELICULAS INFANTILES': 'Infantiles',
            'PISO 7': 'Piso 7',
            'PRESTAMO EN SALA 2026': 'Préstamo en Sala',
            'DOCUMENTALES': 'Documentales',
            'IDIOMAS': 'Idiomas',
            'ESTUDIO  GHIBLI': 'Studio Ghibli',
            'PELICULAS CHINAS': 'Cine Chino',
            'RUSAS': 'Cine Ruso'
        }
        data['category_display'] = category_map.get(self.pdf_category, self.pdf_category)

        return data


class EnrichmentResult(BaseModel):
    """Result of OMDB enrichment for a single movie."""
    movie: Movie
    success: bool
    error_message: Optional[str] = None


class ProcessingSummary(BaseModel):
    """Summary of batch processing results."""
    source_pdf: str
    total: int
    enriched: int
    failed: int
    potential_matches: int = 0


class CatalogIndex(BaseModel):
    """Index of all movies across all PDFs."""
    movies: list[Movie]
    sources: list[PDFSource]
    categories: list[str]
    total_count: int
    enriched_count: int

    def to_json(self, output_path: str) -> None:
        """Export catalog to JSON file for ObservableJS."""
        import json
        from pathlib import Path

        data = {
            'movies': [m.to_observable_dict() for m in self.movies],
            'sources': [s.model_dump() for s in self.sources],
            'categories': self.categories,
            'total_count': self.total_count,
            'enriched_count': self.enriched_count,
            'metadata': {
                'enrichment_rate': self.enriched_count / max(self.total_count, 1)
            }
        }

        Path(output_path).write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )
