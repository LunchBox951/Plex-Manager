import os
import shutil
import time

class Movie:
    def __init__(self, item):
        self.plex_item = item
        self.title = item.title
        self.last_viewed = item.lastViewedAt if hasattr(item, 'lastViewedAt') else None
        self.file_path = item.media[0].parts[0].file if item.media[0].parts else None
    
    def delete(self):
        """Deletes the movie file and its parent folder from disk."""
        if self.file_path:
            try:
                # Get the parent folder of the movie file
                movie_folder = os.path.dirname(self.file_path)

                # Delete the entire movie folder
                shutil.rmtree(movie_folder)
                print(f"Deleted movie: {self.title}")
            except Exception as e:
                print(f"Error deleting movie {self.title}: {e}")
        else:
            print(f"No file path found for movie {self.title}")
    
class TVShow:
    class Episode:
        def __init__(self, episode_item):
            self.title = episode_item.title
            self.season_number = episode_item.seasonNumber
            self.episode_number = episode_item.episodeNumber
            self.last_viewed = episode_item.lastViewedAt if hasattr(episode_item, 'lastViewedAt') else None
            self.file_path = episode_item.media[0].parts[0].file if episode_item.media[0].parts else None

        def delete(self):
            """Deletes the episode file from disk and cleans up empty folders."""
            if self.file_path:
                try:
                    # Get the season and show folders
                    season_folder = os.path.dirname(self.file_path)
                    show_folder = os.path.dirname(season_folder)
                    
                    # Delete the episode file
                    os.remove(self.file_path)
                    print(f"Deleted: S{self.season_number:02d}E{self.episode_number:02d} - {self.title}")
                    
                    # Check if season folder is empty and delete it
                    if os.path.exists(season_folder) and not os.listdir(season_folder):
                        os.rmdir(season_folder)
                        print(f"Deleted empty season folder: {os.path.basename(season_folder)}")
                        
                        # Check if show folder is empty and delete it
                        if os.path.exists(show_folder) and not os.listdir(show_folder):
                            os.rmdir(show_folder)
                            print(f"Deleted empty show folder: {os.path.basename(show_folder)}")
                except Exception as e:
                    print(f"Error deleting episode {self.title}: {e}")
            else:
                print(f"No file path found for episode {self.title}")

    class Season:
        def __init__(self, season_item):
            self.title = season_item.title
            self.season_number = season_item.seasonNumber if hasattr(season_item, 'seasonNumber') else None
            self.episodes = [TVShow.Episode(ep) for ep in season_item.episodes()]

    def __init__(self, item):
        self.title = item.title
        self.seasons = [TVShow.Season(season) for season in item.seasons()]

DAYS_TO_SECONDS = 24 * 60 * 60
# 24 hours x 60 minutes x 60 seconds

# Helper functions
def get_movies_to_delete(movies: list[Movie], days_threshold: int) -> list[Movie]:
    """Returns a list of movies that haven't been viewed in the specified number of days."""
    to_delete = []
    current_time = time.time()
    threshold_seconds = days_threshold * DAYS_TO_SECONDS

    for movie in movies:
        if movie.last_viewed is not None:
            last_viewed_time = movie.last_viewed.timestamp()
            if (current_time - last_viewed_time) > threshold_seconds:
                to_delete.append(movie)
    
    return to_delete

def get_episodes_to_delete(tv_shows: list[TVShow], days_threshold: int) -> list[TVShow.Episode]:
    """Returns a list of TV show episodes that haven't been viewed in the specified number of days."""
    to_delete = []
    current_time = time.time()
    threshold_seconds = days_threshold * DAYS_TO_SECONDS

    for show in tv_shows:
        for season in show.seasons:
            for episode in season.episodes:
                if episode.last_viewed is not None:
                    last_viewed_time = episode.last_viewed.timestamp()
                    if (current_time - last_viewed_time) > threshold_seconds:
                        to_delete.append(episode)
    
    return to_delete