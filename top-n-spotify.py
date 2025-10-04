import os
import sys

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth


def main():
    """Single main function to run the script."""

    load_dotenv()

    client_id = os.getenv("SPOTIPY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Error: Missing credentials. Make sure you have a .env file with SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET.")
        return

    if len(sys.argv) < 3:
        print("Error: Missing arguments.")
        print("Usage: uv run top-n-spotify.py \"<artist name>\" <number_of_songs>")
        print("Example: uv run top-n-spotify.py \"Daft Punk\" 20")
        return

    artist_arg = sys.argv[1]
    try:
        top_n_arg = int(sys.argv[2])
    except ValueError:
        print("Error: The second argument (top-n) must be an integer.")
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
    unique_by_id_tracks = {track['id']: track for track in all_tracks}.values()
    sorted_tracks = sorted(unique_by_id_tracks, key=lambda x: x['popularity'], reverse=True)

    # We take a larger slice initially to have more tracks to filter through
    initial_top_tracks = sorted_tracks[:top_n_arg * 2] # Grab more to ensure we can find enough unique names

    final_tracks = []
    seen_names = set()
    for track in initial_top_tracks:
        if len(final_tracks) >= top_n_arg:
            break  # Stop once we have enough tracks
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
