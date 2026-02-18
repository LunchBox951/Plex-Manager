1. When getting the homepage, downloading the cache images takes a while, likely due to operating in single thread.
 - In src/main_apy.py /api/trending/movies and /api/trending/tv we use a for loop without threading to execute very instance of download_image(). If we used async or multithreading, we can speed this up tremendously
    - Weigh the choices between async and multithreading
*** COMPLETE ***

2. Add logic for separation of "ANIME" from regular TV
 - A special .env path for ANIME
 - Not every server will use this, so it's not necessary. We can use logic like "if environment variable exists" for special functions that surround ANIME
    - For anime specifically, the default language will almost always be "Japanese"
        - this means that scoring in selecting anime will have to be slightly different.
            - Japanese is the default. x 1
            - Dual audio (english and japanese) is x 2
    - This should only work on tv shows - anime movies are still going to show up in the movies directory

3. Have an "Upgrade" option for media - automatically upgrade media if better media is available
 - Anime should auto upgrade to Dual audio if available online but not in the files
    - come up with a scoring system so we don't overbloat our files
 - Other media could upgrade to a higher resolution as long as it doesn't overbloat the files
 - A possible way to score torrent files based on a "auto upgrade" system:
    - Size score:
        - old_size = 15 GB (example)
        - new_size = 20 GB
        - scoring_multiplier = old_size / new_size
    - Resolution score:
        - old_resolution = 1080p (example)
        - new_resolution = 2160p (or 4k)
        - scoring_multiplier = 2
    - Resolution score (another example):
        - old_resolution = 720p (example)
        - new_resolution = 2160p (or 4k)
        - scoring_multiplier = 4
 - This prototype would ensure better media floats to the top of our sorted list before attempting new torrents
    - This is to be combined with the existing system - This way seed count is still important
 - If better media is found, the logic flow should go as follows:
    - Step 1: check if there is actually an upgrade (ie, 1080p -> 4k, or smaller download size, or japanese -> dual audio)
    - Step 2: start new media download
    - Step 3: new media downloaded - delete old media from plex library
    - Step 4: replace deleted media with new media
 - This can be a scheduled task that we run once per day.

4. After login, we default to the dashboard and not the homepage

5. On mobile devices, the popup for the login does not close properly, possibly improve workflow
 - Possible ```landing -> auth_popup -> home```
 - Furthermore, constantly checking if we have a valid login every few seconds is problematic. We could have a new template ```auth_valid.html``` which submits an API call saying login was successful and then triggering the redirect
 *** COMPLETE ***

6. Add "Settings" option to the sidebar
 - Controlls various settings that can be adjusted to the user's wishes
    - Remove all "magic numbers" and replace them with a config file that can be changed via the web
        - IE. "delete after 30 days" can be changed
        - IE. Scheduled tasks can be adjusted

7. Add "Console" tab to the sidebar
 - This will have a stripped down console that can show debug messages to users to allow easier troubleshooting
 *** Started - Not complete ***