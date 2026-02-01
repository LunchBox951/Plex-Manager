import os
import shutil
import time
from typing import Optional
from sqlalchemy.orm import Session

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
def get_movies_to_delete(movies: list[Movie], days_threshold: int, db: Optional[Session] = None) -> list[Movie]:
    """Returns a list of movies that haven't been viewed in the specified number of days."""
    from src.retention import get_effective_retention
    from src.models import MediaRequest
    
    to_delete = []
    current_time = time.time()
    threshold_seconds = days_threshold * DAYS_TO_SECONDS

    for movie in movies:
        # Check retention system protection first
        if db:
            try:
                # Try to find media request by matching title and year
                # Note: This is a basic match, may need fuzzy matching in production
                year = getattr(movie.plex_item, 'year', None)
                media_requests = db.query(MediaRequest).filter(
                    MediaRequest.media_type == 'movie',
                    MediaRequest.title.ilike(f"%{movie.title}%"),
                    MediaRequest.status != 'deleted'
                ).all()
                
                # Check if any request protects this movie
                for request in media_requests:
                    if year and request.year and abs(year - request.year) <= 1:
                        # Found matching request, check effective retention
                        effective_retention, protected = get_effective_retention(
                            db, request.tmdb_id, 'movie'
                        )
                        
                        if protected or effective_retention == 'forever':
                            print(f"Skipping {movie.title} - protected by retention policy")
                            continue  # Skip to next movie
                        
                        # If watch_once or watch_as_released, let retention system handle it
                        # Don't apply legacy time-based deletion
                        print(f"Skipping {movie.title} - managed by retention system")
                        continue
            except Exception as e:
                print(f"Error checking retention for {movie.title}: {e}")
                # Continue with legacy logic if retention check fails
        
        # Legacy time-based deletion for media without retention policies
        if movie.last_viewed is not None:
            last_viewed_time = movie.last_viewed.timestamp()
            if (current_time - last_viewed_time) > threshold_seconds:
                to_delete.append(movie)
    
    return to_delete

def get_episodes_to_delete(tv_shows: list[TVShow], days_threshold: int, db: Optional[Session] = None) -> list[TVShow.Episode]:
    """Returns a list of TV show episodes that haven't been viewed in the specified number of days."""
    from src.retention import get_effective_retention
    from src.models import MediaRequest, EpisodeRetention
    
    to_delete = []
    current_time = time.time()
    threshold_seconds = days_threshold * DAYS_TO_SECONDS

    for show in tv_shows:
        # Check retention system for this show
        if db:
            try:
                media_requests = db.query(MediaRequest).filter(
                    MediaRequest.media_type == 'tv',
                    MediaRequest.title.ilike(f"%{show.title}%"),
                    MediaRequest.status != 'deleted'
                ).all()
                
                # Build protection map for episodes
                protected_episodes = set()
                retention_managed_episodes = set()
                
                for request in media_requests:
                    # Check show-level retention
                    show_retention, show_protected = get_effective_retention(
                        db, request.tmdb_id, 'tv'
                    )
                    
                    if show_protected or show_retention == 'forever':
                        # Entire show is protected
                        print(f"Skipping {show.title} - protected by retention policy")
                        continue  # Skip this entire show
                    
                    # Check for episode-specific overrides
                    episode_overrides = db.query(EpisodeRetention).filter(
                        EpisodeRetention.media_request_id == request.id
                    ).all()
                    
                    for override in episode_overrides:
                        ep_key = (override.season_number, override.episode_number)
                        ep_retention, ep_protected = get_effective_retention(
                            db, request.tmdb_id, 'tv',
                            override.season_number, override.episode_number
                        )
                        
                        if ep_protected or ep_retention == 'forever':
                            protected_episodes.add(ep_key)
                        else:
                            # Episode has retention policy, let retention system handle it
                            retention_managed_episodes.add(ep_key)
                
            except Exception as e:
                print(f"Error checking retention for {show.title}: {e}")
                protected_episodes = set()
                retention_managed_episodes = set()
        else:
            protected_episodes = set()
            retention_managed_episodes = set()
        
        # Apply legacy deletion logic to unprotected episodes
        for season in show.seasons:
            for episode in season.episodes:
                ep_key = (episode.season_number, episode.episode_number)
                
                # Skip protected episodes
                if ep_key in protected_episodes:
                    continue
                
                # Skip episodes managed by retention system
                if ep_key in retention_managed_episodes:
                    continue
                
                # Legacy time-based deletion
                if episode.last_viewed is not None:
                    last_viewed_time = episode.last_viewed.timestamp()
                    if (current_time - last_viewed_time) > threshold_seconds:
                        to_delete.append(episode)
    
    return to_delete