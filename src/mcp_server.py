"""
MCP Server for LLM-assisted movie catalog enrichment.
Provides tools for intelligent movie matching using LLM reasoning + OMDB.
"""

import json
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from omdb_client import search_movie_bilingual, get_movie_details, find_best_fuzzy_match, enrich_movie_with_omdb, search_director_filmography
from source_of_truth import lookup_movie, update_movie
from models import Movie
from tmdb_client import enrich_movie_with_tmdb, search_person, get_person_movie_credits
from tmdb_pipeline import get_unique_directors_from_csv, load_director_cache, fetch_director_filmography
from reconciliation import compare_matches, tag_conflict_resolution, get_all_conflicts, load_catalog_data


app = Server("movie-catalog-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name="analyze_and_match_movie",
            description="""Analyze a movie title from PDF extraction and find the best OMDB match.
            
Use this when:
- The title looks garbled, incomplete, or has extraction artifacts
- Direct OMDB search returned no results
- You need to disambiguate between multiple similar titles
- The title is in Spanish but OMDB might have it in English

The tool uses LLM reasoning to normalize the title, then searches OMDB
with multiple strategies (direct, fuzzy, bilingual).""",
            inputSchema={
                "type": "object",
                "properties": {
                    "raw_title": {
                        "type": "string",
                        "description": "The raw movie title extracted from PDF (may contain artifacts)"
                    },
                    "director_hint": {
                        "type": "string",
                        "description": "Optional director name from PDF context"
                    },
                    "year_hint": {
                        "type": "string",
                        "description": "Optional year or decade hint from PDF (e.g., '1990s', '2020')"
                    },
                    "genre_hint": {
                        "type": "string",
                        "description": "Optional genre from PDF category (e.g., 'Documentary', 'Animation')"
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional additional context from surrounding PDF text"
                    }
                },
                "required": ["raw_title"]
            }
        ),
        Tool(
            name="batch_analyze_titles",
            description="Analyze multiple movie titles at once for batch processing",
            inputSchema={
                "type": "object",
                "properties": {
                    "titles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "raw_title": {"type": "string"},
                                "director_hint": {"type": "string"},
                                "source_pdf": {"type": "string"}
                            },
                            "required": ["raw_title"]
                        },
                        "description": "List of movie titles to analyze"
                    }
                },
                "required": ["titles"]
            }
        ),
        Tool(
            name="get_failed_matches_report",
            description="Get a report of movies that failed OMDB enrichment for manual review",
            inputSchema={
                "type": "object",
                "properties": {
                    "catalog_json_path": {
                        "type": "string",
                        "description": "Path to the catalog.json file",
                        "default": "data/final_results/catalog.json"
                    },
                    "pdf_filter": {
                        "type": "string",
                        "description": "Optional: filter to specific PDF file"
                    }
                }
            }
        ),
        Tool(
            name="detect_title_patterns",
            description="Analyze a movie title for common OCR artifacts, special characters, and casing issues.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The title to analyze"
                    }
                },
                "required": ["title"]
            }
        ),
        Tool(
            name="match_by_director_filmography",
            description="""Search a director's filmography on OMDB and find the best title match.

Use this as a fallback when:
- Direct title search failed or returned false positives
- The title is ambiguous or partially extracted
- You have a reliable director name but an uncertain title

The tool:
1. Searches OMDB using the title query + director last name as hints
2. Fetches details for candidates and verifies the director field
3. Scores each candidate by title similarity (+ bonus if director matches)
4. Returns ranked candidates so the LLM can pick the best one

The LLM should reason: 'Which of these films directed by <director> best matches <raw_title>?'""",
            inputSchema={
                "type": "object",
                "properties": {
                    "raw_title": {
                        "type": "string",
                        "description": "The raw or cleaned movie title to match"
                    },
                    "director": {
                        "type": "string",
                        "description": "Director name (from CSV/PDF context)"
                    },
                    "min_score": {
                        "type": "integer",
                        "description": "Minimum fuzzy title similarity score 0-100 (default 60)",
                        "default": 60
                    }
                },
                "required": ["raw_title", "director"]
            }
        ),
        Tool(
            name="confirm_match",
            description="Confirm a correct movie match and save it to the Source of Truth catalog.",
            inputSchema={
                "type": "object",
                "properties": {
                    "raw_title": {
                        "type": "string",
                        "description": "The original raw title from the PDF"
                    },
                    "imdb_id": {
                        "type": "string",
                        "description": "The correct IMDb ID (tt1234567)"
                    }
                },
                "required": ["raw_title", "imdb_id"]
            }
        ),
        Tool(
            name="get_cine_directors",
            description="Returns list of unique directors extracted from CINE.pdf catalog. Use this to understand the director landscape before enrichment.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="fetch_tmdb_filmography",
            description="Fetch a director's complete filmography from TMDB API. Searches for the director and returns all their movies with titles, original titles, and years.",
            inputSchema={
                "type": "object",
                "properties": {
                    "director": {
                        "type": "string",
                        "description": "Director name to search for"
                    },
                    "use_cache": {
                        "type": "boolean",
                        "description": "Whether to use cached results (default: true)",
                        "default": True
                    }
                },
                "required": ["director"]
            }
        ),
        Tool(
            name="match_movie_by_director_tmdb",
            description="Match a movie title against a director's TMDB filmography. Searches for the director, fetches their filmography, and finds the best fuzzy match for the title.",
            inputSchema={
                "type": "object",
                "properties": {
                    "raw_title": {
                        "type": "string",
                        "description": "Movie title from the catalog"
                    },
                    "director": {
                        "type": "string",
                        "description": "Director name"
                    },
                    "year_hint": {
                        "type": "string",
                        "description": "Optional year to help disambiguate"
                    }
                },
                "required": ["raw_title", "director"]
            }
        ),
        Tool(
            name="compare_and_resolve_match",
            description="Compare OMDB and TMDB matches for a specific movie, calculate confidence scores for both, and provide reasoning about which match is more likely correct. Tags conflicts for manual review when APIs disagree.",
            inputSchema={
                "type": "object",
                "properties": {
                    "raw_title": {
                        "type": "string",
                        "description": "Movie title from the catalog"
                    },
                    "director_hint": {
                        "type": "string",
                        "description": "Optional director name for verification"
                    }
                },
                "required": ["raw_title"]
            }
        ),
        Tool(
            name="get_tmdb_match_report",
            description="Get a comprehensive report comparing TMDB vs OMDB match rates and confidence distributions. Shows statistics on how many movies were matched by each pipeline.",
            inputSchema={
                "type": "object",
                "properties": {
                    "catalog_json_path": {
                        "type": "string",
                        "description": "Path to catalog.json file",
                        "default": "data/final_results/catalog.json"
                    },
                    "tmdb_catalog_path": {
                        "type": "string",
                        "description": "Path to catalog_tmdb.json file",
                        "default": "data/final_results/catalog_tmdb.json"
                    }
                }
            }
        ),
        Tool(
            name="get_conflicts_for_review",
            description="Get all tagged conflicts between OMDB and TMDB matches that require manual review. Use this to see which movies have disagreements between the two APIs.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle MCP tool calls."""
    
    if name == "analyze_and_match_movie":
        return await handle_analyze_and_match(arguments)
    elif name == "batch_analyze_titles":
        return await handle_batch_analyze(arguments)
    elif name == "get_failed_matches_report":
        return await handle_failed_report(arguments)
    elif name == "detect_title_patterns":
        return await handle_detect_patterns(arguments)
    elif name == "match_by_director_filmography":
        return await handle_match_by_director(arguments)
    elif name == "confirm_match":
        return await handle_confirm_match(arguments)
    elif name == "get_cine_directors":
        return await handle_get_cine_directors(arguments)
    elif name == "fetch_tmdb_filmography":
        return await handle_fetch_tmdb_filmography(arguments)
    elif name == "match_movie_by_director_tmdb":
        return await handle_match_movie_by_director_tmdb(arguments)
    elif name == "compare_and_resolve_match":
        return await handle_compare_and_resolve_match(arguments)
    elif name == "get_tmdb_match_report":
        return await handle_get_tmdb_match_report(arguments)
    elif name == "get_conflicts_for_review":
        return await handle_get_conflicts_for_review(arguments)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def handle_analyze_and_match(args: dict) -> list[TextContent]:
    """
    Analyze a raw title and find best OMDB match using multiple strategies.
    
    This is the core LLM-assisted matching logic:
    1. Check Source of Truth (SoT) first
    2. Use LLM reasoning (via the prompt) to normalize/correct the title
    3. Try bilingual search (Spanish -> English fallback)
    4. Use fuzzy matching for broad results
    5. Return best match with confidence score
    """
    raw_title = args.get("raw_title", "").strip()
    director_hint = args.get("director_hint", "").strip()
    year_hint = args.get("year_hint", "").strip()
    genre_hint = args.get("genre_hint", "").strip()
    context = args.get("context", "").strip()
    
    if not raw_title:
        return [TextContent(type="text", text="Error: raw_title is required")]

    # STEP 1: Check Source of Truth
    sot_match = lookup_movie(raw_title)
    if sot_match:
        result = {
            "source_of_truth_match": True,
            "imdb_id": sot_match.get("imdb_id"),
            "title": sot_match.get("matched_title"),
            "match_type": sot_match.get("match_type"),
            "full_data": sot_match.get("full_data"),
            "recommendation": "Use this verified match from the Source of Truth."
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
    
    # Build LLM reasoning prompt for title normalization
    analysis_prompt = f"""Analyze this extracted movie title and find the correct OMDB match.

RAW EXTRACTED TITLE: "{raw_title}"
{director_hint and f'DIRECTOR HINT: {director_hint}' or ''}
{year_hint and f'YEAR HINT: {year_hint}' or ''}
{genre_hint and f'GENRE HINT: {genre_hint}' or ''}
{context and f'CONTEXT: {context}' or ''}

Task:
1. Clean/normalize the title (remove PDF extraction artifacts)
2. If Spanish title, provide likely English equivalent
3. Consider director hints to disambiguate
4. Suggest the most likely correct title for OMDB search

Respond in this JSON format:
{{
    "cleaned_title": "the normalized title",
    "likely_english_title": "English version if original is Spanish",
    "search_strategy": "exact|fuzzy|bilingual",
    "confidence_reasoning": "why this interpretation is likely correct",
    "alternative_titles": ["list", "of", "other", "possibilities"]
}}"""

    # Return the analysis prompt for the LLM to use
    result = {
        "analysis_prompt": analysis_prompt,
        "search_strategies": [],
        "recommendations": [
            "1. Review the analysis prompt above",
            "2. Use LLM reasoning to determine the correct title",
            "3. Try search_movie_bilingual with the cleaned title",
            "4. If no exact match, use find_best_fuzzy_match for broad search",
            "5. Verify director matches if director_hint provided"
        ],
        "next_steps": {
            "primary_search": raw_title,
            "fallback_search": f"Try variations of '{raw_title}' without articles",
            "verify_fields": ["Director", "Year", "Genre"]
        }
    }
    
    # Also attempt direct search to give immediate feedback
    direct_result = search_movie_bilingual(raw_title) or {}

    if direct_result.get("imdbID"):
        details = get_movie_details(direct_result["imdbID"]) or {}
        result["immediate_match"] = {
            "found": True,
            "imdb_id": direct_result.get("imdbID"),
            "title": details.get("Title") or direct_result.get("matched_title"),
            "year": details.get("Year"),
            "director": details.get("Director"),
            "match_type": direct_result.get("match_type"),
            "confidence": "high" if direct_result.get("match_type") in ("exact_spanish", "no_article", "english_fallback") else "medium"
        }
    else:
        from omdb_client import broad_search_movie
        candidates = broad_search_movie(raw_title) or []
        fuzzy_best = find_best_fuzzy_match(raw_title, candidates) if candidates else None
        if fuzzy_best:
            result["immediate_match"] = {
                "found": False,
                "fuzzy_candidate": fuzzy_best,
                "recommendation": "Review fuzzy candidate and confirm if correct"
            }
        else:
            result["immediate_match"] = {
                "found": False,
                "recommendation": "Requires manual LLM analysis - use analysis_prompt"
            }
    
    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def handle_batch_analyze(args: dict) -> list[TextContent]:
    """Process multiple titles in batch."""
    titles = args.get("titles", [])
    
    if not titles:
        return [TextContent(type="text", text="No titles provided")]
    
    results = []
    for item in titles[:10]:  # Limit to 10 at a time
        raw_title = item.get("raw_title", "")
        if not raw_title:
            continue
            
        # Quick direct search
        search_result = search_movie_bilingual(raw_title) or {}
        found = bool(search_result.get("imdbID"))
        
        results.append({
            "raw_title": raw_title,
            "source_pdf": item.get("source_pdf", ""),
            "status": "enriched" if found else "failed",
            "match": search_result.get("matched_title"),
            "imdb_id": search_result.get("imdbID"),
            "match_type": search_result.get("match_type")
        })
    
    # Summary
    enriched_count = sum(1 for r in results if r["status"] == "enriched")
    
    summary = {
        "batch_summary": {
            "total_processed": len(results),
            "enriched": enriched_count,
            "failed": len(results) - enriched_count,
            "success_rate": enriched_count / len(results) if results else 0
        },
        "results": results,
        "failed_titles": [r["raw_title"] for r in results if r["status"] == "failed"]
    }
    
    return [TextContent(type="text", text=json.dumps(summary, indent=2, ensure_ascii=False))]


async def handle_failed_report(args: dict) -> list[TextContent]:
    """Generate a report of failed matches for manual review."""
    catalog_path = args.get("catalog_json_path", "data/final_results/catalog.json")
    pdf_filter = args.get("pdf_filter", "")
    
    try:
        if not os.path.exists(catalog_path):
             return [TextContent(type="text", text=f"Catalog file not found at {catalog_path}. Run the pipeline first.")]
        with open(catalog_path, 'r', encoding='utf-8') as f:
            catalog = json.load(f)
    except Exception as e:
        return [TextContent(type="text", text=f"Error loading catalog: {e}")]
    
    movies = catalog.get("movies", [])
    
    # Filter to non-enriched movies
    failed_movies = [m for m in movies if not m.get("enriched")]
    
    if pdf_filter:
        failed_movies = [m for m in failed_movies if pdf_filter in m.get("source_pdf", "")]
    
    # Group by source PDF
    by_pdf = {}
    for m in failed_movies:
        pdf = m.get("source_pdf", "Unknown")
        if pdf not in by_pdf:
            by_pdf[pdf] = []
        by_pdf[pdf].append({
            "title": m.get("title"),
            "pdf_category": m.get("pdf_category"),
            "suggested_search": m.get("title", "").replace(",", "").strip()
        })
    
    report = {
        "total_failed": len(failed_movies),
        "by_pdf": {k: len(v) for k, v in by_pdf.items()},
        "priority_reviews": [
            {
                "pdf": pdf,
                "count": len(titles),
                "sample_titles": titles[:5]  # First 5 as examples
            }
            for pdf, titles in sorted(by_pdf.items(), key=lambda x: -len(x[1]))[:5]
        ],
        "ready_for_llm_analysis": [
            {
                "raw_title": m.get("title"),
                "source_pdf": m.get("source_pdf"),
                "category": m.get("pdf_category")
            }
            for m in failed_movies[:20]  # Top 20 for immediate attention
        ]
    }
    
    return [TextContent(type="text", text=json.dumps(report, indent=2, ensure_ascii=False))]


async def handle_detect_patterns(args: dict) -> list[TextContent]:
    """Analyze a title for common OCR artifacts and patterns."""
    import re
    title = args.get("title", "")
    if not title:
        return [TextContent(type="text", text="Error: title is required")]

    patterns_found = []
    suggested_fixes = []

    # 1. Mixed casing/OCR artifacts
    if re.search(r'[a-z][A-Z]', title):
        patterns_found.append("Possible joined words (MixedCase)")
        # Suggest split if possible, but for now just note it
    
    # 2. Number substitutions
    if 'l' in title.lower() and re.search(r'\d', title):
        patterns_found.append("Possible 'l' for '1' substitution")
        suggested_fixes.append(re.sub(r'l', '1', title, flags=re.IGNORECASE))

    if '0' in title and 'o' in title.lower():
        patterns_found.append("Possible '0' for 'o' substitution")
        suggested_fixes.append(re.sub(r'0', 'o', title, flags=re.IGNORECASE))

    # 3. Special characters
    special_chars = re.findall(r'[^a-zA-Z0-9\s,.\'\"\-]', title)
    if special_chars:
        patterns_found.append(f"Special characters detected: {''.join(set(special_chars))}")
        suggested_fixes.append(re.sub(r'[^a-zA-Z0-9\s,.\'\"\-]', '', title))

    # 4. Trailing artifacts
    if re.search(r'[\.\-=:]{2,}$', title):
        patterns_found.append("Trailing punctuation artifacts")
        suggested_fixes.append(title.rstrip('. -=:'))

    result = {
        "title": title,
        "patterns_detected": patterns_found,
        "suggested_fixes": list(set(suggested_fixes)),
        "recommendation": "Apply suggested fixes or use LLM to clean the title further."
    }
    
    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def handle_match_by_director(args: dict) -> list[TextContent]:
    """
    Use director filmography to find the best title match.
    Implements the strategy:
      'Which movies has this director made whose title resembles what we have?'
    """
    import re

    raw_title = args.get("raw_title", "").strip()
    director = args.get("director", "").strip()
    min_score = int(args.get("min_score", 60))

    if not raw_title or not director:
        return [TextContent(type="text", text="Error: raw_title and director are required")]

    # Clean director field — strip common PDF artifacts like "Dir.", trailing commas, birth years
    director_clean = re.sub(r'^(Dir\.|dir\.|Escrita y Dir\.|Guión y Dir\.|prod\. y)\s*', '', director, flags=re.IGNORECASE)
    director_clean = re.sub(r',\s*\d{4}-?$', '', director_clean).strip().rstrip('.')

    # Also clean the title query — strip article suffixes like "Zona Muerta.La"
    title_clean = re.sub(r'([a-záéíóúüñA-ZÁÉÍÓÚÜÑ])\.([A-ZÁÉÍÓÚÜÑ])', r'\1 \2', raw_title)
    match = re.search(r'^(.*),\s*(El|La|Los|Las|The|Un|Una)\.?$', title_clean, re.IGNORECASE)
    if match:
        title_clean = f"{match.group(2)} {match.group(1)}".strip()
    title_clean = title_clean.strip().rstrip('.')

    candidates = search_director_filmography(director_clean, title_clean, min_score=min_score)

    if not candidates:
        result = {
            "status": "no_candidates",
            "raw_title": raw_title,
            "director": director_clean,
            "cleaned_title": title_clean,
            "message": (
                f"No OMDB candidates found for '{title_clean}' with director '{director_clean}'. "
                "Suggestions: try a broader title fragment, check director spelling, "
                "or use confirm_match with a known IMDb ID."
            )
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    # Build LLM reasoning guidance
    top = candidates[:5]
    reasoning_context = (
        f"We are looking for a movie titled '{raw_title}' directed by '{director_clean}'.\n"
        f"The cleaned search title is '{title_clean}'.\n\n"
        "OMDB returned these candidates (sorted by title similarity + director match bonus):\n"
    )
    for i, c in enumerate(top, 1):
        director_tag = " ✓ director confirmed" if c['director_matched'] else " ✗ director not confirmed"
        reasoning_context += (
            f"  {i}. [{c['score']}] {c['title']} ({c['year']}) — "
            f"IMDb: {c['imdbID']} — Director: {c['director']}{director_tag}\n"
        )
    reasoning_context += (
        "\nLLM task: Pick the candidate that best matches the raw title semantically. "
        "Prefer candidates where the director is confirmed. "
        "If confident, call confirm_match with the chosen imdb_id."
    )

    result = {
        "status": "candidates_found",
        "raw_title": raw_title,
        "director": director_clean,
        "cleaned_title": title_clean,
        "top_candidate": top[0] if top else None,
        "all_candidates": top,
        "reasoning_guidance": reasoning_context,
        "auto_confirm_eligible": (
            top[0]['score'] >= 90 and top[0]['director_matched']
        ) if top else False
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def handle_confirm_match(args: dict) -> list[TextContent]:
    """Confirm a movie match and update the Source of Truth."""
    import re
    import csv as csv_mod

    raw_title = args.get("raw_title", "")
    imdb_id = args.get("imdb_id", "")

    if not raw_title or not imdb_id:
        return [TextContent(type="text", text="Error: raw_title and imdb_id are required")]

    # Fetch full data from OMDB to store in SoT
    details = get_movie_details(imdb_id)
    if not details:
        return [TextContent(type="text", text=f"Error: Could not fetch details for IMDb ID {imdb_id}")]

    # Look up catalogue_id from CSV
    csv_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results', 'cine_hybrid_method.csv')
    pdf_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'pdfs', 'CINE.pdf')
    catalogue_id = None
    page_number = None

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in csv_mod.DictReader(f):
                if row.get('title_spanish', '').strip() == raw_title:
                    catalogue_id = int(row['id'])
                    break
    except Exception:
        pass

    # Look up page from PDF index
    if catalogue_id:
        try:
            from pypdf import PdfReader
            reader = PdfReader(pdf_path)
            id_to_page: dict[int, int] = {}
            for pnum, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                for m in re.finditer(r'(?:^|\n)\s*(\d{1,4})(?=\s|[A-ZÁÉÍÓÚÜÑa-záéíóúüñ¿¡])', text):
                    n = int(m.group(1))
                    if 1 <= n <= 9999 and n not in id_to_page:
                        id_to_page[n] = pnum
            page_number = id_to_page.get(catalogue_id)
        except Exception:
            pass

    success = update_movie(
        raw_title, details,
        match_type="mcp_confirmed",
        catalogue="CINE.pdf",
        catalogue_id=catalogue_id,
        page_number=page_number,
    )

    if success:
        meta = f" | catalogue_id={catalogue_id}, page={page_number}" if catalogue_id else ""
        return [TextContent(type="text", text=f"Successfully confirmed '{raw_title}' as '{details.get('Title')}' ({imdb_id}) and updated Source of Truth.{meta}")]
    else:
        return [TextContent(type="text", text="Error: Failed to update Source of Truth.")]


async def handle_get_cine_directors(args: dict) -> list[TextContent]:
    """Get unique directors from CINE.pdf catalog."""
    try:
        directors = get_unique_directors_from_csv()
        result = {
            "total_directors": len(directors),
            "directors": directors,
            "sample": directors[:20] if len(directors) > 20 else directors
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def handle_fetch_tmdb_filmography(args: dict) -> list[TextContent]:
    """Fetch a director's filmography from TMDB."""
    director = args.get("director", "").strip()
    use_cache = args.get("use_cache", True)
    
    if not director:
        return [TextContent(type="text", text="Error: director is required")]
    
    try:
        filmography = fetch_director_filmography(director, use_cache=use_cache)
        if not filmography:
            return [TextContent(type="text", text=f"No TMDB results found for director: {director}")]
        
        # Return summary + full filmography
        result = {
            "director": director,
            "tmdb_name": filmography.get("tmdb_name"),
            "tmdb_person_id": filmography.get("tmdb_person_id"),
            "popularity": filmography.get("popularity"),
            "movie_count": filmography.get("movie_count"),
            "filmography": filmography.get("filmography", [])[:10]  # First 10 for brevity
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def handle_match_movie_by_director_tmdb(args: dict) -> list[TextContent]:
    """Match a movie title against a director's TMDB filmography."""
    raw_title = args.get("raw_title", "").strip()
    director = args.get("director", "").strip()
    year_hint = args.get("year_hint", "").strip()
    
    if not raw_title or not director:
        return [TextContent(type="text", text="Error: raw_title and director are required")]
    
    try:
        result = enrich_movie_with_tmdb(raw_title, director, year_hint if year_hint else None)
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def handle_compare_and_resolve_match(args: dict) -> list[TextContent]:
    """Compare OMDB and TMDB matches for a specific movie."""
    raw_title = args.get("raw_title", "").strip()
    director_hint = args.get("director_hint", "").strip()
    
    if not raw_title:
        return [TextContent(type="text", text="Error: raw_title is required")]
    
    try:
        comparison = compare_matches(raw_title, director_hint)
        
        # Tag conflict if present
        if comparison.get("conflict"):
            tag_conflict_resolution(raw_title, comparison)
        
        return [TextContent(type="text", text=json.dumps(comparison, indent=2, ensure_ascii=False))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def handle_get_tmdb_match_report(args: dict) -> list[TextContent]:
    """Get comprehensive report comparing TMDB vs OMDB match rates."""
    catalog_path = args.get("catalog_json_path", "data/final_results/catalog.json")
    tmdb_path = args.get("tmdb_catalog_path", "data/final_results/catalog_tmdb.json")
    
    try:
        omdb_data, tmdb_data = load_catalog_data()
        
        # Calculate statistics
        total_omdb = len([m for m in omdb_data.values() if m.get("enriched")])
        total_tmdb = len([m for m in tmdb_data.values() if m.get("tmdb_matched")])
        
        # High confidence matches
        high_conf_omdb = sum(1 for m in omdb_data.values() 
                            if m.get("enriched") and m.get("match_type") in ["exact", "exact_spanish"])
        high_conf_tmdb = sum(1 for m in tmdb_data.values() 
                            if m.get("tmdb_matched") and m.get("confidence", 0) >= 90)
        
        # Calculate overlap
        all_titles = set(omdb_data.keys()) | set(tmdb_data.keys())
        matched_by_both = 0
        matched_only_omdb = 0
        matched_only_tmdb = 0
        unmatched = 0
        
        for title in all_titles:
            omdb_match = title in omdb_data and omdb_data[title].get("enriched")
            tmdb_match = title in tmdb_data and tmdb_data[title].get("tmdb_matched")
            
            if omdb_match and tmdb_match:
                matched_by_both += 1
            elif omdb_match:
                matched_only_omdb += 1
            elif tmdb_match:
                matched_only_tmdb += 1
            else:
                unmatched += 1
        
        result = {
            "total_movies": len(all_titles),
            "omdb_stats": {
                "total_matched": total_omdb,
                "high_confidence": high_conf_omdb
            },
            "tmdb_stats": {
                "total_matched": total_tmdb,
                "high_confidence": high_conf_tmdb
            },
            "overlap": {
                "matched_by_both": matched_by_both,
                "matched_only_omdb": matched_only_omdb,
                "matched_only_tmdb": matched_only_tmdb,
                "unmatched": unmatched
            },
            "files": {
                "omdb_catalog": str(catalog_path),
                "tmdb_catalog": str(tmdb_path)
            }
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def handle_get_conflicts_for_review(args: dict) -> list[TextContent]:
    """Get all tagged conflicts requiring manual review."""
    try:
        conflicts = get_all_conflicts()
        
        if not conflicts:
            return [TextContent(type="text", text="No conflicts found. Run compare_and_resolve_match on movies to tag conflicts.")]
        
        # Group by status
        pending = [c for c in conflicts if c.get("status") == "pending_review"]
        resolved = [c for c in conflicts if c.get("status") == "resolved"]
        
        result = {
            "total_conflicts": len(conflicts),
            "pending_review": len(pending),
            "resolved": len(resolved),
            "conflicts": pending[:10]  # First 10 pending conflicts
        }
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    """Run MCP server."""
    from mcp.server.models import InitializationOptions
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
