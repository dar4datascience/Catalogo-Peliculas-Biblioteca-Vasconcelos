import os
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results')
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'final_results', 'all_movies.csv')

def combine_all_successful_files():
    """Combines all successful and suggestions_successful CSVs into one."""
    all_dfs = []
    
    # Find all relevant CSV files
    successful_files = [f for f in os.listdir(DATA_DIR) if f.endswith('_successful.csv')]
    
    print("Found the following files to combine:")
    for filename in successful_files:
        print(f"- {filename}")
        filepath = os.path.join(DATA_DIR, filename)
        try:
            df = pd.read_csv(filepath)
            all_dfs.append(df)
        except pd.errors.EmptyDataError:
            print(f"  (Skipping empty file: {filename})")

    if not all_dfs:
        print("No data found to combine. Exiting.")
        return

    # Combine all dataframes
    combined_df = pd.concat(all_dfs, ignore_index=True)

    # Drop duplicates based on IMDb ID, keeping the first occurrence
    initial_rows = len(combined_df)
    combined_df.drop_duplicates(subset=['imdbID'], keep='first', inplace=True)
    final_rows = len(combined_df)

    print(f"\nCombined {len(all_dfs)} files.")
    print(f"Removed {initial_rows - final_rows} duplicate entries.")

    # Save the final master file
    combined_df.to_csv(OUTPUT_FILE, index=False)
    print(f"Final combined data saved to {OUTPUT_FILE} with {final_rows} unique movies.")

if __name__ == "__main__":
    combine_all_successful_files()
