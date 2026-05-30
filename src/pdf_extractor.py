import re
from pathlib import Path

import camelot
import pandas as pd
from PyPDF2 import PdfReader


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
