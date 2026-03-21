import os
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from omdb_client import search_movie_id, get_movie_details

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results')

def process_suggestion_file(filepath):
    """Processes a single cleanup suggestions file."""
    df = pd.read_csv(filepath)
    successful_data = []
    failed_titles = []
    source_name = os.path.basename(filepath).replace('_cleanup_suggestions.csv', '')

    print(f"--- Enriching suggestions for {source_name} ---")

    with ThreadPoolExecutor(max_workers=10) as executor:
        tasks = {executor.submit(search_movie_id, row['Likely Corrected Title']): row for _, row in df.iterrows()}
        for future in as_completed(tasks):
            row = tasks[future]
            original_title = row['Original Failed Title']
            corrected_title = row['Likely Corrected Title']
            imdb_id = future.result()

            if imdb_id:
                details = get_movie_details(imdb_id)
                if details:
                    details['OriginalTitle'] = original_title
                    successful_data.append(details)
                else:
                    failed_titles.append(corrected_title)
            else:
                failed_titles.append(corrected_title)

    # Save results for this source
    if successful_data:
        success_path = os.path.join(DATA_DIR, f"{source_name}_suggestions_successful.csv")
        pd.DataFrame(successful_data).to_csv(success_path, index=False)
        print(f"Saved {len(successful_data)} successful suggestions to {success_path}")

    if failed_titles:
        fail_path = os.path.join(DATA_DIR, f"{source_name}_suggestions_failed.csv")
        pd.DataFrame({'FailedCorrectedTitle': failed_titles}).to_csv(fail_path, index=False)
        print(f"Saved {len(failed_titles)} failed suggestions to {fail_path}")

def enrich_all_suggestions():
    suggestion_files = [f for f in os.listdir(DATA_DIR) if f.endswith('_cleanup_suggestions.csv')]
    for filename in suggestion_files:
        process_suggestion_file(os.path.join(DATA_DIR, filename))

    print("\nAll suggestion files have been processed.")

if __name__ == "__main__":
    enrich_all_suggestions()
