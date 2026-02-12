Here are a list of torrents that have failed due to various reasons:

1. Predator: Badlands
    - The reason is due to the colon in the name, which is forbidden by the OS
        - Filter out unaccepted characters in search engines as well as the OS as a fix

2. Chainsaw Man - The Movie Reze Arc
    - The reason is due to language issues. It attempts to download another language other than japanese or english
        - We can check TMDB for native language
        - We can cross reference this against our desired language (english)
        - Outlines for this plan are located in #POSSIBLE_OPTIMIZATIONS.md
            - Optimization number 3 - Anime fix
            - Piggyback off these changes to ensure if the native language is not english, look for dual audio
            - If dual audio option is not available, then exclude other languages (in this case, japanese should be default)
    - The scoring system's choice for what to download is strange, and unintentional
        - It grabs a 1080p, 1010MB file with 3 seeders
            - This is especially strange since a 1080p, 1.5GB torrent exists on the indexer list that has 500 seeders.
            - This indicates we might need to re-evaluate the scoring system
    - The issue could derive from the search having the dash (`-`) while the torrent does not. 
        - Excluding odd characters (like the issue with predator badlands) might fix this issue.