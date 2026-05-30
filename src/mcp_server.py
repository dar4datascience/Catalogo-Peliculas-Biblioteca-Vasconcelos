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

from omdb_client import search_movie_bilingual, get_movie_details, find_best_fuzzy_match
from models import Movie


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
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def handle_analyze_and_match(args: dict) -> list[TextContent]:
    """
    Analyze a raw title and find best OMDB match using multiple strategies.
    
    This is the core LLM-assisted matching logic:
    1. Use LLM reasoning (via the prompt) to normalize/correct the title
    2. Try bilingual search (Spanish -> English fallback)
    3. Use fuzzy matching for broad results
    4. Return best match with confidence score
    """
    raw_title = args.get("raw_title", "").strip()
    director_hint = args.get("director_hint", "").strip()
    year_hint = args.get("year_hint", "").strip()
    genre_hint = args.get("genre_hint", "").strip()
    context = args.get("context", "").strip()
    
    if not raw_title:
        return [TextContent(type="text", text="Error: raw_title is required")]
    
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
    direct_result = search_movie_bilingual(raw_title)
    
    if direct_result.get("enriched"):
        movie_data = direct_result.get("data", {})
        result["immediate_match"] = {
            "found": True,
            "imdb_id": movie_data.get("imdbID"),
            "title": movie_data.get("Title"),
            "year": movie_data.get("Year"),
            "director": movie_data.get("Director"),
            "match_type": direct_result.get("match_type"),
            "confidence": "high" if direct_result.get("match_type") == "exact" else "medium"
        }
    else:
        # Try fuzzy search
        fuzzy_matches = find_best_fuzzy_match(raw_title, raw_title)
        if fuzzy_matches:
            result["fuzzy_candidates"] = fuzzy_matches[:3]
            result["immediate_match"] = {
                "found": False,
                "suggested_candidates": len(fuzzy_matches),
                "recommendation": "Review fuzzy matches and select best candidate"
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
        search_result = search_movie_bilingual(raw_title)
        
        results.append({
            "raw_title": raw_title,
            "source_pdf": item.get("source_pdf", ""),
            "status": "enriched" if search_result.get("enriched") else "failed",
            "match": search_result.get("matched_title") if search_result.get("enriched") else None,
            "imdb_id": search_result.get("data", {}).get("imdbID") if search_result.get("enriched") else None
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


async def main():
    """Run MCP server."""
    async with stdio_server(server=app) as streams:
        await app.run(
            streams[0],
            streams[1],
            app.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
