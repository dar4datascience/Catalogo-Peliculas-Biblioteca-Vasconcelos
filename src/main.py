import os
import pandas as pd
from pdf_extractor import extract_tables_from_pdf
from omdb_client import search_movie_id, get_movie_details

PDF_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

def process_pdfs(pdf_directory):
    """
    Processes all PDF files in a directory to extract movie data and enrich it.
    """
    all_movie_data = []

    for filename in os.listdir(pdf_directory):
        if filename.endswith('.pdf'):
            pdf_path = os.path.join(pdf_directory, filename)
            print(f"Processing {pdf_path}...")
            tables = extract_tables_from_pdf(pdf_path)

            for i, df in enumerate(tables):
                print(f"  Processing Table {i+1}...")
                # This assumes the movie title is in the first column.
                # You may need to adjust the column name or index.
                if not df.empty and 0 in df.columns:
                    for title in df.iloc[:, 0]:
                        if not isinstance(title, str) or not title.strip():
                            continue
                        
                        print(f"    Fetching details for '{title}'...")
                        imdb_id = search_movie_id(title)
                        if imdb_id:
                            details = get_movie_details(imdb_id)
                            if details:
                                details['SourcePDF'] = filename
                                all_movie_data.append(details)
                        else:
                            all_movie_data.append({'Title': title, 'Error': 'IMDb ID not found', 'SourcePDF': filename})

    if all_movie_data:
        output_df = pd.DataFrame(all_movie_data)
        output_path = os.path.join(OUTPUT_DIR, 'movie_data.csv')
        output_df.to_csv(output_path, index=False)
        print(f"\nData saved to {output_path}")
    else:
        print("\nNo movie data was extracted.")

if __name__ == "__main__":
    # Ensure the output directory exists
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    process_pdfs(PDF_DIR)
