1. when a torrent has completed seeding, it is not removed from the database, meaning we get:
 - ``` Error fetching torrent info for 36a7522598abf7cab88eedff4bd3209adf1cb8d6: 'QBittorrentClient' object has no attribute 'torrents_info' ```
 - This is likely happening due to src/qbittorrent.py QBittorrentClient.delete_torrent() deleting the torrent successfully, but no database changes happen to reflect this, meaning each time it monitors the active torrents it's checking for something that doesn't exist.
*** COMPLETE ***

2. Making a request on the homepage does not work. Making a request via the media info page works as intended, meaning we're probably missing an API call.
*** COMPLETE ***

3. Clicking on "Open QBittorrent" on the sidebar does not actually open the web app - figure out how to access the webapp and change the link acordingly.

4. Improve downloading tv shows logic:
- If the user requests the entire show
    - Accept whole series compliations
- If whole series compliation fails
    - For each season in series
        - Attempt downloading season
- If any season failed to download
    - For each episode in season
        - Attempt downloading episode

5. Improve bad torrent handling post download
 - Sometimes a download will happen successfully, but have an issue with the actual file.
    - For example, a good download could have audio sync issues. Or corrupted video
 - If that is the case, we need a way for users to tell the Manager that there is an issue
    - Add a "Report Issue" option to episodes and movies
 - When "Report Issue" API call is made, mark the downloaded torrent as "failed" so it doesn't redownload
    - Delete the media from the plex library
    - Reattempt download, skipping the bad torrent

6. If the downloads folder is full, but we want to download something else, we will get halted due to inefficient storage. This flow needs to be addressed.
 - For example, if there is 2GB remaining in the downloads directory, but we request media that is 20GB:
    - Sort active torrents by age (oldest -> newest)
    - Start trying to clear torrents to make room for 20GB + 10% wiggle room download
    - For active_torrent in sorted_torrents:
        - if currently_downloading:
            - Skip. We need active downloads to complete
        - else:
            - delete the seeding torrent early - take the size of what was cleared and tally it up
        - if cleared_gb >= room_needed:
            - break
 - This prototype would make sure finished downloads are cleared first, and in order from oldest to newest.