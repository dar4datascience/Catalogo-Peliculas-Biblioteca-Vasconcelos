import pandas as pd
import os
import re

INPUT_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results', 'raw_movie_titles.csv')
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'intermediate_results', 'tidied_movie_titles.csv')

TITLE_COUNTS = {
    'RUSAS.pdf': 18,
    'ESTUDIO  GHIBLI.pdf': 17,
    'CINE.pdf': 2241,
    'PRESTAMO EN SALA 2026.pdf': 476
}

# Keywords that make a string less likely to be a title
NEGATIVE_KEYWORDS = [
    r'dir\.', r'prod\.', 'animación', 'aventura', 'comedia', 'drama', 'fantasía',
    'ciencia ficción', 'género', 'director', 'guión', 'tetsuo', 'katayama',
    'suzuki', 'yoshiaki', 'hayao', 'miyazaki', 'takahata', 'goro', 'título',
    'dibujos', 'animación', 'familiar', '‧', ';'
]

def score_title(title):
    """Scores a title based on heuristics. Higher is better."""
    score = 100
    # Penalize for containing negative keywords
    for keyword in NEGATIVE_KEYWORDS:
        if re.search(keyword, title, re.IGNORECASE):
            score -= 20
    # Penalize for being short
    if len(title) < 5:
        score -= 30
    # Penalize for having too many capitalized words (like a sentence)
    if len(re.findall(r'\b[A-Z][a-z]+\b', title)) > 5:
        score -= 10
    # Reward for having quotes, which often indicate a title
    if '"' in title or '“' in title or '”' in title:
        score += 10
    return score

def tidy_up_csv(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"Input file not found: {input_path}")
        return

    df = pd.read_csv(input_path)
    tidied_df = pd.DataFrame(columns=['Title', 'SourcePDF'])

    for source_pdf, group in df.groupby('SourcePDF'):
        print(f"Tidying {source_pdf}...")
        # Score each title in the group
        group['score'] = group['Title'].apply(score_title)

        if source_pdf in TITLE_COUNTS:
            # For known counts, take the top N highest-scoring titles
            limit = TITLE_COUNTS[source_pdf]
            top_group = group.nlargest(limit, 'score')
            tidied_df = pd.concat([tidied_df, top_group[['Title', 'SourcePDF']]], ignore_index=True)
        else:
            # For unknown counts, filter out titles with a low score
            good_titles = group[group['score'] > 50]
            tidied_df = pd.concat([tidied_df, good_titles[['Title', 'SourcePDF']]], ignore_index=True)

    # Final cleanup on the entire dataset
    tidied_df['Title'] = tidied_df['Title'].str.replace('"', '').str.strip()
    tidied_df.drop_duplicates(subset=['Title'], inplace=True)

    tidied_df.to_csv(output_path, index=False)
    print(f"\nTidied data saved to {output_path}")

if __name__ == "__main__":
    tidy_up_csv(INPUT_FILE, OUTPUT_FILE)
