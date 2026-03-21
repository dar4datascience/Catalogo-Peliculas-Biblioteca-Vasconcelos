import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OMDB_API_KEY")
BASE_URL = "http://www.omdbapi.com/"

def _query_omdb(params):
    """Helper function to query the OMDb API and handle responses."""
    try:
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if data.get('Response') == 'True':
            return data
    except requests.exceptions.RequestException as e:
        print(f"Error querying OMDb: {e}")
    return None

def search_movie_id(title):
    """ 
    Searches for a movie's ID using a multi-step exact match process.
    """
    # 1. Direct search
    data = _query_omdb({'t': title, 'apikey': API_KEY})
    if data: 
        return data.get('imdbID')

    # 2. Clean trailing digits and retry
    cleaned_title = re.sub(r'\s+\d+$', '', title).strip()
    if cleaned_title != title:
        data = _query_omdb({'t': cleaned_title, 'apikey': API_KEY})
        if data:
            return data.get('imdbID')

    # 3. Handle swapped titles (e.g., "Title, The") and retry
    if ',' in cleaned_title:
        parts = [part.strip() for part in cleaned_title.split(',')]
        if len(parts) == 2:
            swapped_title = f"{parts[1]} {parts[0]}"
            data = _query_omdb({'t': swapped_title, 'apikey': API_KEY})
            if data:
                return data.get('imdbID')
    return None

def broad_search_movie(title):
    """Performs a broad search and returns all potential matches."""
    cleaned_title = re.sub(r'\s+\d+$', '', title).strip()
    if ',' in cleaned_title:
        parts = [part.strip() for part in cleaned_title.split(',')]
        if len(parts) == 2:
            cleaned_title = f"{parts[1]} {parts[0]}"
            
    search_data = _query_omdb({'s': cleaned_title, 'apikey': API_KEY})
    if search_data and 'Search' in search_data:
        return search_data['Search']
    return None

def get_movie_details(imdb_id):
    """
    Fetches movie details using its Movie ID.

    Args:
        imdb_id (str): The Movie ID of the movie.

    Returns:
        dict: A dictionary containing the movie's details, or None if not found.
    """
    params = {
        'i': imdb_id,
        'plot': 'full',
        'apikey': API_KEY
    }
    try:
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if data.get('Response') == 'True':
            return data
        else:
            print(f"Could not fetch details for Movie ID '{imdb_id}': {data.get('Error')}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching details for Movie ID '{imdb_id}': {e}")
        return None
