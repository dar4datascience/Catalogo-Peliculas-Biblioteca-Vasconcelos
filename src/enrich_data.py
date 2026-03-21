import os
import json
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from omdb_client import search_movie_id, get_movie_details, broad_search_movie

INPUT_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results', 'tidied_movie_titles.csv')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results')

def process_title(title, source_pdf):
    if not isinstance(title, str) or not title.strip():
        return None, None, None

    # 1. Try exact match first
    imdb_id = search_movie_id(title)
    if imdb_id:
        details = get_movie_details(imdb_id)
        if details:
            details['SourcePDF'] = source_pdf
            return details, None, None

    # 2. If no exact match, perform a broad search
    potential_matches = broad_search_movie(title)
    if potential_matches:
        match_list = []
        for match in potential_matches:
            match_list.append({
                'OriginalTitle': title,
                'PotentialTitle': match.get('Title'),
                'Year': match.get('Year'),
                'MovieID': match.get('imdbID'),
                'SourcePDF': source_pdf
            })
        return None, match_list, None

    # 3. If still no match, log as failed
    return None, None, {'Title': title, 'SourcePDF': source_pdf}

def enrich_data(input_file):
    if not os.path.exists(input_file):
        print(f"Error: Input file not found at {input_file}")
        return

    df = pd.read_csv(input_file)
    summary = {}

    for source_pdf, group in df.groupby('SourcePDF'):
        print(f"--- Processing source: {source_pdf} ---")
        successful_data, potential_data, failed_data = [], [], []
        tasks = []

        with ThreadPoolExecutor(max_workers=10) as executor:
            for _, row in group.iterrows():
                tasks.append(executor.submit(process_title, row['Title'], row['SourcePDF']))

            for future in as_completed(tasks):
                success, potential, failed = future.result()
                if success:
                    successful_data.append(success)
                if potential:
                    potential_data.extend(potential)
                if failed:
                    failed_data.append(failed)
        
        source_name = os.path.splitext(source_pdf)[0]
        summary[source_pdf] = {
            'successful': len(successful_data),
            'potential': len(potential_data),
            'failed': len(failed_data)
        }

        if successful_data:
            pd.DataFrame(successful_data).to_csv(os.path.join(OUTPUT_DIR, f'{source_name}_successful.csv'), index=False)
        if potential_data:
            pd.DataFrame(potential_data).to_csv(os.path.join(OUTPUT_DIR, f'{source_name}_potential_matches.csv'), index=False)
        if failed_data:
            pd.DataFrame(failed_data).to_csv(os.path.join(OUTPUT_DIR, f'{source_name}_failed.csv'), index=False)

    summary_path = os.path.join(OUTPUT_DIR, 'processing_summary.json')
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=4)
    
    print(f"\nProcessing complete. Summary saved to {summary_path}")

if __name__ == "__main__":
    enrich_data(INPUT_FILE)
