import argparse
import math
import os
from datetime import datetime

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth


def parse_release_date(date_str: str) -> datetime:
    """Handles different release date precisions (YYYY, YYYY-MM, YYYY-MM-DD)."""
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        parts = date_str.split('-')
        if len(parts) == 1: return datetime(int(parts[0]), 1, 1)
        if len(parts) == 2: return datetime(int(parts[0]), int(parts[1]), 1)
    return datetime.now()


def calculate_custom_score(track: dict, aggressiveness: int) -> float:
    """Calculates a custom score based on a configurable aggressiveness level."""
    popularity = track.get('popularity', 0)

    if aggressiveness == 0:
        return popularity

    release_date_str = track.get('album', {}).get('release_date', '')
    if not release_date_str:
        return popularity

    release_date = parse_release_date(release_date_str)
    days_since_release = (datetime.now() - release_date).days

    if days_since_release < 0:
        days_since_release = 0

    # Add a small constant to avoid math errors with log(0) or 0**...
    age_factor = days_since_release + 2

    if aggressiveness == 1: # Subtle
        multiplier = math.log(math.log(age_factor) + 1)
    elif aggressiveness == 2: # Balanced
        multiplier = math.log(age_factor)
    elif aggressiveness == 3: # Aggressive
        multiplier = math.sqrt(age_factor)
    else: # Default to Balanced if invalid level is given
        multiplier = math.log(age_factor)

    return popularity * multiplier


def main():
    """Single main function to run the script."""
    load_dotenv()

    # --- Professional Argument Parsing ---
    parser = argparse.ArgumentParser(
        description="Creates a Spotify playlist of an artist's top tracks based on popularity and age.",
        formatter_class=argparse.RawTextHelpFormatter # For better help text formatting
    )
    parser.add_argument("artist", type=str, help="The name of the artist (use quotes for multi-word names).")
    parser.add_argument("top_n", type=int, help="The number of tracks to include in the playlist.")
    parser.add_argument(
        "-a", "--aggressiveness", type=int, default=1, choices=[0, 1, 2, 3],
        help="How much to weigh a song's age against its recent popularity.\n"
             "  0: None (pure Spotify popularity - favors newness).\n"
             "  1: Balanced (logarithmic - gently boosts classics).\n"
             "  2: Aggressive (square root - strongly boosts classics).\n"
             "  3: Classics-Focused (power - heavily favors time-tested tracks)."
    )
    args = parser.parse_args()

    artist_arg = args.artist
    top_n_arg = args.top_n
    aggressiveness_arg = args.aggressiveness
    # --- End Argument Parsing ---

    client_id = os.getenv("SPOTIPY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Error: Missing credentials in .env file.")
        return

    playlist_name = f"Top {top_n_arg} {artist_arg}"
    playlist_description = f"The {top_n_arg} most popular tracks by {artist_arg}"

    scope = "playlist-modify-public"

    try:
        auth_manager = SpotifyOAuth(scope=scope)
        sp = spotipy.Spotify(auth_manager=auth_manager)
        user_id = sp.current_user()["id"]
    except OSError as e:
        if e.errno == 48 or 'Address already in use' in str(e):
            print(f"Error: Port {getattr(e, 'port', 'unknown')} is already in use by another program.")
            print("Please stop the other program or see the README for instructions on how to change the port.")
        else:
            print(f"An unexpected OS error occurred: {e}")
        return
    except Exception as e:
        print(f"Error during authentication: {e}")
        print("Please check your .env file and your Redirect URI in the Spotify Dashboard.")
        return

    print(f"  searching for artist: '{artist_arg}'...")
    results = sp.search(q=f'artist:{artist_arg}', type='artist', limit=1)
    if not results['artists']['items']:
        print(f"Could not find artist '{artist_arg}'. Please check the spelling.")
        return

    artist = results['artists']['items'][0]
    artist_id = artist['id']
    print(f"Found artist: {artist['name']} (ID: {artist_id})")

    print("  fetching all albums and singles...")
    all_releases = []
    offset = 0
    while True:
        results = sp.artist_albums(artist_id, album_type='album,single', limit=50, offset=offset)
        all_releases.extend(results['items'])
        if results['next']:
            offset += 50
        else:
            break

    album_ids = [release['id'] for release in all_releases]
    print(f"  found {len(album_ids)} total releases.")

    print("  collecting track IDs from all releases...")
    track_ids = []
    for i in range(0, len(album_ids), 20):
        chunk = album_ids[i:i+20]
        album_details_list = sp.albums(chunk)['albums']
        for album in album_details_list:
            for track in album['tracks']['items']:
                track_ids.append(track['id'])

    print(f"  collected {len(track_ids)} track IDs. Fetching full track details in batches...")

    all_tracks = []
    for i in range(0, len(track_ids), 50):
        chunk = track_ids[i:i+50]
        track_details_list = sp.tracks(chunk)['tracks']
        all_tracks.extend(track_details_list)

    print(f"  found {len(all_tracks)} tracks in total.")

    all_tracks = [track for track in all_tracks if track is not None]
    unique_by_id_tracks = list({track['id']: track for track in all_tracks}.values())

    print(f" calculating custom score for each track with aggressiveness level {aggressiveness_arg}...")

    # Sort by our new custom score, passing the aggressiveness level
    sorted_tracks = sorted(
        unique_by_id_tracks,
        key=lambda t: calculate_custom_score(t, aggressiveness_arg),
        reverse=True
    )

    print(" filtering out duplicate song names...")
    final_tracks = []
    seen_names = set()
    for track in sorted_tracks:
        if len(final_tracks) >= top_n_arg:
            break
        track_name = track['name']
        if track_name not in seen_names:
            final_tracks.append(track)
            seen_names.add(track_name)

    if not final_tracks:
        print("Found no popular tracks for this artist.")
        return

    print(f"Found the top {len(final_tracks)} unique tracks.")

    playlist = sp.user_playlist_create(
        user=user_id,
        name=playlist_name,
        public=True,
        description=playlist_description
    )
    playlist_id = playlist['id']
    playlist_url = playlist['external_urls']['spotify']

    track_uris = [track['uri'] for track in final_tracks]

    for i in range(0, len(track_uris), 100):
        chunk = track_uris[i:i+100]
        sp.playlist_add_items(playlist_id, chunk)

    print("\n🤠🤙 All Done! 😎🤟")
    print(f'Your new playlist "{playlist_name}" is ready.')
    print(f"Listen here: {playlist_url}")
    print("Or check your public playlists on your profile on the Spotify app!")


if __name__ == '__main__':
    main()
