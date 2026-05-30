# PDF Extraction Methods for CINE.pdf - Implementation Summary

## Two Methods Implemented

### Method 1: `extract_cine_regex()` - Regex-Based Line-by-Line
Uses PyPDF2 to extract text and regex patterns to parse each line independently.

**Results:**
- 2244 entries extracted
- 86.5% with director
- 8.4% with English title

**Pros:** Simple, fast
**Cons:** Misses data when entries span multiple lines

---

### Method 2: `extract_cine_hybrid()` - Multi-Line Reconstruction
Uses PyPDF2 with intelligent line reconstruction to handle entries split across lines.

**Results:**
- 2244 entries extracted
- 97.4% with director (better!)
- 14.1% with English title

**Pros:** Handles multi-line entries, superior director extraction
**Cons:** Slightly more complex

---

## Key Implementation Details

### Director Pattern Matching
Multiple variations handled:
- `Dir. Name`
- `dir. Name`
- `Escrita y Dir. Name`
- `Dir. y prod. Name`
- `prod. y guion`

### Bilingual Title Parsing
Two formats supported:
- `Spanish = English` (e.g., "Gánster americano = American gangster")
- `Spanish - English` (e.g., "Un beso más - The last kiss")

### Multi-Line Reconstruction
Critical fix: Preserve trailing spaces when joining PDF lines to avoid "dowe" becoming "dowe" instead of "do we".

---

## Output Files

CSV files saved to `data/intermediate_results/`:
- `cine_regex_method.csv` - Method 1 results
- `cine_hybrid_method.csv` - Method 2 results (recommended)

---

## Recommendation

**Use Method 2 (`extract_cine_hybrid`)** - It achieves 97.4% director extraction vs 86.5% for Method 1, with better handling of multi-line entries and bilingual titles.
