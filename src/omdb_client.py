import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OMDB_API_KEY")
BASE_URL = "http://www.omdbapi.com/"

def search_movie_id(title):
    """
    Searches for a movie's IMDb ID by its title.

    Args:
        title (str): The title of the movie.

    Returns:
        str: The IMDb ID of the movie, or None if not found.
    """
    params = {
        't': title,
        'apikey': API_KEY
    }
    try:
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if data.get('Response') == 'True':
            return data.get('imdbID')
        else:
            print(f"Could not find IMDb ID for '{title}': {data.get('Error')}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error searching for movie '{title}': {e}")
        return None

def get_movie_details(imdb_id):
    """
    Fetches movie details using its IMDb ID.

    Args:
        imdb_id (str): The IMDb ID of the movie.

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
            print(f"Could not fetch details for IMDb ID '{imdb_id}': {data.get('Error')}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching details for IMDb ID '{imdb_id}': {e}")
        return None
