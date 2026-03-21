import os
import re
import pandas as pd
from pdf_extractor import extract_tables_from_pdf

PDF_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

NON_TITLE_KEYWORDS = [
    r'dir\.', r'prod\.', 'animación', 'aventura', 'comedia', 'drama', 'fantasía', 
    'ciencia ficción', 'género', 'director', 'guión', 'tetsuo', 'katayama',
    'suzuki', 'yoshiaki', 'hayao', 'miyazaki', 'takahata', 'goro'
]

def clean_title(text):
    if not isinstance(text, str):
        return ""
    text = text.replace('\n', ' ').strip()
    text = re.sub(r'^\d+[\s\.]*', '', text) # Remove leading numbers
    text = re.sub(r'^[Nn]\.?[oO]?\s*[\.:]?', '', text) # Remove N., No.
    text = re.sub(r'=[^=]*$', '', text) # Remove trailing '=...'
    text = re.sub(r'\([^)]*\)$', '', text) # Remove trailing '(...)'
    return text.strip('",. ')

def is_valid_title(title):
    if not title or len(title) < 4 or title.isdigit(): # Increased min length
        return False
    if title.lower() in ['título', 'title', 'director', 'género']:
        return False
    # If it looks like a list of names, it's probably not a title
    if len(re.findall(r'[A-Z][a-z]+', title)) > 4 and ',' in title:
        return False
    if any(re.search(keyword, title, re.IGNORECASE) for keyword in NON_TITLE_KEYWORDS):
        return False
    return True

def extract_raw_data(pdf_directory):
    raw_data = []
    seen_titles = set()

    for filename in os.listdir(pdf_directory):
        if not filename.endswith('.pdf'):
            continue
        pdf_path = os.path.join(pdf_directory, filename)
        print(f"Processing {pdf_path}...")
        tables = extract_tables_from_pdf(pdf_path)

        for i, df in enumerate(tables):
            print(f"  Processing Table {i+1}...")
            if not df.empty:
                # Focus only on the first column
                for item in df.iloc[:, 0]:
                    cleaned = clean_title(item)
                    if is_valid_title(cleaned) and cleaned not in seen_titles:
                        raw_data.append({'Title': cleaned, 'SourcePDF': filename})
                        seen_titles.add(cleaned)

    if raw_data:
        output_df = pd.DataFrame(raw_data)
        output_path = os.path.join(OUTPUT_DIR, 'raw_movie_titles.csv')
        output_df.to_csv(output_path, index=False)
        print(f"\nRaw movie titles saved to {output_path}")
    else:
        print("\nNo movie titles were extracted.")

if __name__ == "__main__":
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    extract_raw_data(PDF_DIR)
