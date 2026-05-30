import re
from pathlib import Path
from typing import Optional

import camelot
import pandas as pd
from PyPDF2 import PdfReader


# Director pattern variations for regex extraction
DIR_PATTERNS = [
    r'Director:',  # Director: (capital D)
    r'Dir\.\s*y\s*prod\.',
    r'Dir\.',  # Dir.
    r'dir\.',  # dir.
    r'Dir:',  # Dir: (colon, no period)
    r'dir:',  # dir:
    r'Dir,',  # Dir, (comma)
    r'Dir\.{2,}',  # Dir.. (double period)
    r'Escrita\s+y\s*Dir\.',  # Escrita y Dir.
    r'Escrita\s+y\s*dir\.',  # Escrita y dir.
    r'Escrita\s+y\s*Dir',  # Escrita y Dir (no period)
    r'prod\.\s*y\s*guion',
    r'escrito\s+por',
    r'Dir\s+',  # Dir (just space, no punctuation)
]
DIR_PATTERN_COMBINED = '|'.join(DIR_PATTERNS)


def extract_tables_from_pdf(pdf_path):
    """
    Extracts tables from a given PDF file.

    Args:
        pdf_path (str): The file path to the PDF.

    Returns:
        list: A list of pandas DataFrames, each representing a table.
    """
    try:
        tables = camelot.read_pdf(pdf_path, pages='all', flavor='stream')
        return [table.df for table in tables]
    except Exception as e:
        print(f"Error extracting tables from {pdf_path}: {e}")
        return []


def extract_pdf_metadata(pdf_path):
    """
    Extract metadata from PDF file.

    Args:
        pdf_path (str): Path to PDF file.

    Returns:
        dict: Metadata including title, author, page_count, etc.
    """
    try:
        reader = PdfReader(pdf_path)
        meta = reader.metadata
        return {
            'title': meta.title if meta else None,
            'author': meta.author if meta else None,
            'subject': meta.subject if meta else None,
            'page_count': len(reader.pages),
            'file_name': Path(pdf_path).name
        }
    except Exception as e:
        print(f"Error reading PDF metadata from {pdf_path}: {e}")
        return {'file_name': Path(pdf_path).name, 'page_count': 0}


def extract_text_from_page(pdf_path, page_num):
    """
    Extract text from a specific page.

    Args:
        pdf_path (str): Path to PDF file.
        page_num (int): Page number (0-indexed).

    Returns:
        str: Text content of the page.
    """
    try:
        reader = PdfReader(pdf_path)
        if page_num < len(reader.pages):
            return reader.pages[page_num].extract_text() or ""
        return ""
    except Exception as e:
        print(f"Error extracting text from page {page_num} in {pdf_path}: {e}")
        return ""


def find_index_page(pdf_path):
    """
    Attempt to find the index/table of contents page in a PDF.
    Looks for keywords like 'indice', 'contenido', 'index' in first few pages.

    Args:
        pdf_path (str): Path to PDF file.

    Returns:
        int: Page number of index (0-indexed), or -1 if not found.
    """
    index_keywords = ['indice', 'contenido', 'index', 'tabla de contenido',
                      'contenidos', 'indice general', 'lista de peliculas']

    try:
        reader = PdfReader(pdf_path)
        # Check first 5 pages for index
        for page_num in range(min(5, len(reader.pages))):
            text = reader.pages[page_num].extract_text() or ""
            text_lower = text.lower()
            if any(keyword in text_lower for keyword in index_keywords):
                return page_num
        return -1
    except Exception as e:
        print(f"Error finding index in {pdf_path}: {e}")
        return -1


def extract_index_entries(pdf_path):
    """
    Extract index/table of contents entries from PDF.
    Tries to parse entries with format: "Category/Title ... PageNumber"

    Args:
        pdf_path (str): Path to PDF file.

    Returns:
        list: List of dicts with 'title', 'page' keys.
    """
    index_page = find_index_page(pdf_path)
    if index_page == -1:
        return []

    try:
        text = extract_text_from_page(pdf_path, index_page)
        entries = []

        # Common patterns for index entries:
        # "Category Name ............ 5"
        # "Title .......... 10"
        lines = text.split('\n')

        for line in lines:
            # Match patterns like "Title ... 123" or "Category .... 5"
            match = re.match(r'^(.+?)\s*[\.\s]+(\d+)\s*$', line.strip())
            if match:
                title = match.group(1).strip()
                page = int(match.group(2))
                # Filter out header/footer lines
                if len(title) > 3 and not any(x in title.lower() for x in ['pagina', 'page', 'indice', 'contenido']):
                    entries.append({'title': title, 'page': page})

        return entries
    except Exception as e:
        print(f"Error extracting index entries from {pdf_path}: {e}")
        return []


def get_context_around_title(pdf_path, title, context_pages=1):
    """
    Get surrounding pages and metadata for a movie title.
    Useful for understanding which section/category a movie belongs to.

    Args:
        pdf_path (str): Path to PDF file.
        title (str): Movie title to search for.
        context_pages (int): Number of pages before/after to include.

    Returns:
        dict: Information about where the title appears in the PDF.
    """
    try:
        reader = PdfReader(pdf_path)
        title_lower = title.lower()

        for page_num, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if title_lower in text.lower():
                # Found the title, gather context
                start_page = max(0, page_num - context_pages)
                end_page = min(len(reader.pages), page_num + context_pages + 1)

                context_texts = []
                for p in range(start_page, end_page):
                    context_texts.append(reader.pages[p].extract_text() or "")

                return {
                    'found': True,
                    'page_number': page_num + 1,  # 1-indexed for humans
                    'pdf_file': Path(pdf_path).name,
                    'context_pages': list(range(start_page + 1, end_page + 1)),
                    'context_text': '\n'.join(context_texts)
                }

        return {'found': False, 'pdf_file': Path(pdf_path).name}
    except Exception as e:
        print(f"Error searching for '{title}' in {pdf_path}: {e}")
        return {'found': False, 'pdf_file': Path(pdf_path).name, 'error': str(e)}


# ============================================================================
# METHOD 1: Regex-Based Text Extraction for CINE.pdf
# ============================================================================

def extract_cine_regex(pdf_path: str) -> pd.DataFrame:
    """
    Method 1: Extract movie entries from CINE.pdf using regex-based parsing.

    Handles mixed formatting:
    - ID sometimes attached to title: "817Gánster americano"
    - Bilingual titles: "Spanish = English" or "Spanish - English"
    - Director variations: "Dir.", "Escrita y Dir.", "Dir. y prod."

    Args:
        pdf_path: Path to CINE.pdf

    Returns:
        DataFrame with columns: id, title_spanish, title_english, director, raw_line
    """
    entries = []
    reader = PdfReader(pdf_path)

    for page in reader.pages:
        text = page.extract_text() or ""
        lines = text.split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Try to extract entry
            entry = _parse_cine_line(line)
            if entry:
                entries.append(entry)

    return pd.DataFrame(entries)


def _parse_cine_line(line: str) -> Optional[dict]:
    """
    Parse a single line from CINE.pdf into structured data.

    Pattern: ID Title[ = or - English] Director_Pattern Director_Name[; extra]
    """
    # Normalize non-breaking spaces to regular spaces
    line = line.replace('\xa0', ' ')

    # Skip lines without numeric ID at start
    if not re.match(r'^\d+', line):
        return None

    # Extract ID (first digits)
    id_match = re.match(r'^(\d+)\s*', line)
    if not id_match:
        return None

    movie_id = int(id_match.group(1))
    remaining = line[id_match.end():]

    # Special case: If remaining starts with "Dir." immediately, the title IS the ID
    # e.g., "1984Dir. Michael Radford" -> ID=1984, Title="1984"
    if re.match(r'^Dir\.', remaining, re.IGNORECASE):
        title_part = str(movie_id)  # Title is the year/movie name
        dir_match = re.search(f'({DIR_PATTERN_COMBINED})', remaining, re.IGNORECASE)
        if dir_match:
            dir_part = remaining[dir_match.start():]
        else:
            dir_part = remaining
        dir_name = _extract_director_name(dir_part)
        return {
            'id': movie_id,
            'title_spanish': title_part,
            'title_english': None,
            'director': dir_name,
            'raw_line': line
        }

    # Find director pattern to split title from director
    dir_regex = re.compile(f'({DIR_PATTERN_COMBINED})', re.IGNORECASE)
    dir_match = dir_regex.search(remaining)

    if not dir_match:
        # No director found - might be a malformed entry
        return {
            'id': movie_id,
            'title_spanish': remaining.strip(),
            'title_english': None,
            'director': None,
            'raw_line': line
        }

    # Split title and director parts
    title_part = remaining[:dir_match.start()].strip()
    dir_part = remaining[dir_match.start():].strip()

    # Parse bilingual title
    title_spanish, title_english = _parse_bilingual_title(title_part)

    # Extract director name (everything after director pattern, up to ; or end)
    dir_name = _extract_director_name(dir_part)

    return {
        'id': movie_id,
        'title_spanish': title_spanish,
        'title_english': title_english,
        'director': dir_name,
        'raw_line': line
    }


def _parse_bilingual_title(title_part: str) -> tuple:
    """
    Parse title into Spanish and English parts.
    Handles: "Spanish = English" or "Spanish - English"
    Also handles incomplete English titles (truncated)
    """
    # Pattern: equals sign separator (most common)
    equals_match = re.match(r'^(.*?)\s*=\s*(.+)$', title_part)
    if equals_match:
        spanish = equals_match.group(1).strip()
        english = equals_match.group(2).strip()
        # Clean up incomplete English titles
        if english.lower() in ['where do', 'he', 'the', 'that into you', 'heaven']:
            # Truncated - don't split
            return (title_part, None)
        return (spanish, english)

    # Pattern: dash separator (e.g., "Un beso más - The last kiss")
    # Only match if English part starts with capital letter (article or proper noun)
    dash_match = re.match(r'^(.+?)\s+-\s+([A-Z][a-zA-Z\s]+)$', title_part)
    if dash_match:
        spanish = dash_match.group(1).strip()
        english = dash_match.group(2).strip()
        # Validate English part looks like a title (at least 2 words or proper noun)
        if len(english.split()) >= 2 or english.lower() not in ['el', 'la', 'los', 'las', 'un', 'una']:
            return (spanish, english)

    # Single title (Spanish only)
    return (title_part, None)


def _extract_director_name(dir_part: str) -> Optional[str]:
    """
    Extract director name from director field.
    Removes the director pattern prefix and trailing metadata.
    Handles non-breaking spaces (\xa0) and various punctuation.
    """
    # Normalize non-breaking spaces to regular spaces
    dir_part = dir_part.replace('\xa0', ' ')

    # Remove director pattern prefix
    dir_regex = re.compile(f'^({DIR_PATTERN_COMBINED})\\s*', re.IGNORECASE)
    name = dir_regex.sub('', dir_part).strip()

    # Strip trailing metadata (after ; or . at end)
    name = re.split(r'\s*[;.]', name)[0].strip()

    return name if name else None


# ============================================================================
# METHOD 2: Hybrid Text+Regex Extraction (PyPDF2 + Smart Line Reconstruction)
# ============================================================================

def extract_cine_hybrid(pdf_path: str) -> pd.DataFrame:
    """
    Method 2: Extract movie entries using PyPDF2 with multi-line entry reconstruction.

    This method handles entries that span multiple lines by:
    1. Detecting continuation lines (don't start with numeric ID)
    2. Reconstructing complete entries before parsing
    3. Using the same parsing logic as Method 1

    Args:
        pdf_path: Path to CINE.pdf

    Returns:
        DataFrame with columns: id, title_spanish, title_english, director, raw_line
    """
    entries = []
    reader = PdfReader(pdf_path)

    current_entry_lines = []

    for page in reader.pages:
        text = page.extract_text() or ""
        lines = text.split('\n')

        for line in lines:
            # Only strip leading space, preserve trailing space for word reconstruction
            line = line.lstrip()
            if not line:
                continue

            # Check if this is a new entry (starts with numeric ID)
            # ID must be followed by: space, end of string, OR any character (including ¿, letters, etc.)
            # Avoid false positives like "2 : El Gran Houdini" being parsed as ID 2
            if re.match(r'^\d+(?:\s|$|.)', line) and not re.match(r'^\d+\s*:\s', line):
                # Process previous entry if exists
                if current_entry_lines:
                    entry = _parse_reconstructed_entry(current_entry_lines)
                    if entry:
                        entries.append(entry)
                    current_entry_lines = []

                # Start new entry
                current_entry_lines = [line]
            else:
                # Continuation of previous entry
                if current_entry_lines:
                    current_entry_lines.append(line)

        # Process last entry on page
        if current_entry_lines:
            entry = _parse_reconstructed_entry(current_entry_lines)
            if entry:
                entries.append(entry)
            current_entry_lines = []

    return pd.DataFrame(entries)


def _parse_reconstructed_entry(lines: list) -> Optional[dict]:
    """
    Parse a multi-line entry that has been reconstructed.
    Joins lines with space, handling word boundaries intelligently.
    PDF splits words across lines (e.g., 'Wh' + 'ere' -> 'Where')
    """
    if not lines:
        return None

    raw_line = lines[0]
    for i in range(1, len(lines)):
        next_line = lines[i]

        # Check last char of current and first char of next
        prev_last = raw_line[-1] if raw_line else ' '
        next_first = next_line[0] if next_line else ' '

        # Case 1: Word split across lines (e.g., "Wh" + "ere")
        # Join without space if prev ends with lowercase and next starts with lowercase
        word_continuation = prev_last.islower() and next_first.islower()

        # Case 2: Already have space or next starts with space/punctuation
        has_separator = prev_last.isspace() or next_first.isspace() or next_first in '.,;:!?'

        # Case 3: Separator characters (= or - at end of line)
        is_separator = prev_last in '=-'

        if word_continuation or has_separator or is_separator:
            raw_line += next_line
        else:
            raw_line += ' ' + next_line

    return _parse_cine_line(raw_line)


# ============================================================================
# Comparison and Testing Utilities
# ============================================================================

def compare_extraction_methods(pdf_path: str, sample_size: int = 50) -> dict:
    """
    Run both extraction methods and compare results.

    Returns:
        dict with metrics for both methods
    """
    print("Running Method 1: Regex-based extraction...")
    df_regex = extract_cine_regex(pdf_path)
    print(f"  Extracted {len(df_regex)} entries")

    print("Running Method 2: Hybrid (multi-line reconstruction)...")
    df_hybrid = extract_cine_hybrid(pdf_path)
    print(f"  Extracted {len(df_hybrid)} entries")

    # Calculate metrics
    metrics = {
        'regex': {
            'total_entries': len(df_regex),
            'with_director': df_regex['director'].notna().sum(),
            'with_english_title': df_regex['title_english'].notna().sum(),
            'sample': df_regex.head(sample_size).to_dict('records')
        },
        'hybrid': {
            'total_entries': len(df_hybrid),
            'with_director': df_hybrid['director'].notna().sum(),
            'with_english_title': df_hybrid['title_english'].notna().sum(),
            'sample': df_hybrid.head(sample_size).to_dict('records')
        }
    }

    return metrics
