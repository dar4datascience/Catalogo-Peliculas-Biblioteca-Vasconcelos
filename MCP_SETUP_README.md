# Windsurf MCP Setup for Movie Catalog

## Using Method 2 (Recommended)

The hybrid extraction method has been implemented in `src/pdf_extractor.py`:

```python
from pdf_extractor import extract_cine_hybrid

# Extract all 2241 movie entries from CINE.pdf
df = extract_cine_hybrid('data/pdfs/CINE.pdf')

# Results:
# - 2243 entries extracted (2 extra due to data quality issues in source)
# - 97.9% have director information (2197/2243)
# - 14.1% have bilingual titles
```

### Why Method 2?
- **97.9% director extraction** vs 87.0% for Method 1
- Handles multi-line entries properly
- Correctly reconstructs words split across PDF lines
- Better bilingual title parsing

---

## Setting Up Windsurf MCP

### Quick Setup

Run the setup script:

```bash
cd /home/chonkydev/Documents/Github_Repos/Catalogo-Peliculas-Biblioteca-Vasconcelos
./setup-windsurf-mcp.sh
```

### Manual Setup

If the script doesn't work, manually create the config file:

```bash
mkdir -p ~/.codeium/windsurf
```

Create `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "movie-catalog": {
      "command": "python3",
      "args": [
        "/home/chonkydev/Documents/Github_Repos/Catalogo-Peliculas-Biblioteca-Vasconcelos/src/mcp_server.py"
      ],
      "env": {
        "PYTHONPATH": "/home/chonkydev/Documents/Github_Repos/Catalogo-Peliculas-Biblioteca-Vasconcelos/src"
      },
      "cwd": "/home/chonkydev/Documents/Github_Repos/Catalogo-Peliculas-Biblioteca-Vasconcelos"
    }
  }
}
```

### After Setup

1. **Restart Windsurf** if it's already running
2. Open the **Cascade panel**
3. Click the **MCP icon** in the top right
4. The **"movie-catalog"** MCP should appear in the list
5. Enable the tools you want to use

---

## Available MCP Tools

### 1. `analyze_and_match_movie`
Analyze a movie title from PDF extraction and find the best OMDB match.

**Use when:**
- Title looks garbled or has extraction artifacts
- Direct OMDB search returned no results
- Need to disambiguate between similar titles
- Title is in Spanish but OMDB might have it in English

**Input:**
- `raw_title` (required): The extracted movie title
- `director_hint` (optional): Director name from PDF
- `year_hint` (optional): Year/decade hint
- `genre_hint` (optional): Genre from PDF category
- `context` (optional): Additional context

### 2. `batch_analyze_titles`
Process multiple movie titles at once for batch processing.

**Input:**
- `titles`: Array of objects with `raw_title`, `director_hint`, `source_pdf`

### 3. `get_failed_matches_report`
Get a report of movies that failed OMDB enrichment.

**Input:**
- `catalog_json_path`: Path to catalog.json (default: "data/final_results/catalog.json")
- `pdf_filter`: Optional filter to specific PDF file

### 4. `detect_title_patterns`
Analyze a title for common OCR artifacts and patterns.

**Input:**
- `title`: The title to analyze

### 5. `confirm_match`
Confirm a correct movie match and save it to the Source of Truth.

**Input:**
- `raw_title`: The original raw title from PDF
- `imdb_id`: The correct IMDb ID (tt1234567)

---

## Example Usage in Windsurf

Once configured, you can use the MCP tools in Cascade:

```
@movie-catalog analyze_and_match_movie {
  "raw_title": "Gánster americano = American gangster",
  "director_hint": "Ridley Scott"
}
```

Or for batch processing:

```
@movie-catalog batch_analyze_titles {
  "titles": [
    {"raw_title": "A corazón abierto", "director_hint": "Susanne Bier"},
    {"raw_title": "Cómo matar a un ruiseñor", "director_hint": "Robert Mulligan"}
  ]
}
```

---

## Troubleshooting

### MCP server not appearing
- Verify the `mcp_config.json` file exists at `~/.codeium/windsurf/mcp_config.json`
- Check that the paths in the config are correct
- Restart Windsurf

### Tools not working
- Ensure you're in the correct workspace
- Check that Python dependencies are installed: `pip install mcp requests`
- Verify OMDB API key is set if needed

### Extraction issues
- The hybrid method handles most edge cases
- For entries without directors, the PDF may have malformed data
- The duplicate ID 1984 is a source data issue (two different movies with same ID)
