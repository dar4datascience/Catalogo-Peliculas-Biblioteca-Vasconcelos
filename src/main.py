import os
import pandas as pd
from pdf_extractor import extract_tables_from_pdf

PDF_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

def extract_raw_data(pdf_directory):
    """
    Extracts raw movie titles from all PDFs in a directory.
    """
    raw_data = []

    for filename in os.listdir(pdf_directory):
        if filename.endswith('.pdf'):
            pdf_path = os.path.join(pdf_directory, filename)
            print(f"Processing {pdf_path}...")
            tables = extract_tables_from_pdf(pdf_path)

            for i, df in enumerate(tables):
                print(f"  Processing Table {i+1}...")
                if not df.empty and 0 in df.columns:
                    for title in df.iloc[:, 0]:
                        if isinstance(title, str) and title.strip():
                            raw_data.append({'Title': title, 'SourcePDF': filename})

    if raw_data:
        output_df = pd.DataFrame(raw_data)
        output_path = os.path.join(OUTPUT_DIR, 'raw_movie_titles.csv')
        output_df.to_csv(output_path, index=False)
        print(f"\nRaw movie titles saved to {output_path}")
    else:
        print("\nNo movie titles were extracted.")

if __name__ == "__main__":
    # Ensure the output directory exists
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    extract_raw_data(PDF_DIR)
