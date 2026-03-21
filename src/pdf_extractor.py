import camelot
import pandas as pd

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
