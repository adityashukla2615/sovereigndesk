"""Real-data layer: source adapters, raw cache, seed snapshot, quality tags and refresh jobs.

Data flows live → cache → seed: adapters fetch from the official sources (retrying), raw
responses are cached on disk, parsed rows land in ``observations``, and the committed seed
snapshot fills anything that has never been fetched, so the terminal always boots offline.
"""
