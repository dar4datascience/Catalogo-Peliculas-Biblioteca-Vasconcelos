import os
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from omdb_client import search_movie_id, get_movie_details

INPUT_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'failed_cases.csv')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

def process_title(title, source_pdf):
    """
    Fetches details for a single movie title.
    """
    if not isinstance(title, str) or not title.strip():
        return None

    print(f"    Fetching details for '{title}'...")
    imdb_id = search_movie_id(title)
    if imdb_id:
        details = get_movie_details(imdb_id)
        if details:
            details['SourcePDF'] = source_pdf
            return details
    
    return {'Title': title, 'Error': 'Movie ID not found', 'SourcePDF': source_pdf}

def enrich_data(input_file):
    """
    Enriches the raw movie data with details from OMDb.
    """
    if not os.path.exists(input_file):
        print(f"Error: Input file not found at {input_file}")
        return

    df = pd.read_csv(input_file)
    successful_data = []
    failed_data = []
    tasks = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        for index, row in df.iterrows():
            tasks.append(executor.submit(process_title, row['Title'], row['SourcePDF']))

        for future in as_completed(tasks):
            result = future.result()
            if result:
                if 'Error' in result:
                    failed_data.append(result)
                else:
                    successful_data.append(result)

    if successful_data:
        output_df = pd.DataFrame(successful_data)
        output_path = os.path.join(OUTPUT_DIR, 'movie_data_retried.csv')
        output_df.to_csv(output_path, index=False)
        print(f"\nSuccessfully processed data saved to {output_path}")
    else:
        print("\nNo movie data was successfully extracted.")

    if failed_data:
        failed_df = pd.DataFrame(failed_data)
        failed_path = os.path.join(OUTPUT_DIR, 'failed_cases_final.csv')
        failed_df.to_csv(failed_path, index=False)
        print(f"Failed cases saved to {failed_path}")
    else:
        print("No failed cases.")

if __name__ == "__main__":
    enrich_data(INPUT_FILE)
