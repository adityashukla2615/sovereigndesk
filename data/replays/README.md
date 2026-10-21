Replay datasets for Module D (`REPLAY <ID>`), one folder per episode and version:

    <ID>/v1/episode.yaml    window, drivers, targets, annotations (with sources) and cited inputs
    <ID>/v1/series/*.csv    date,value
    <ID>/v1/manifest.json   each series' source, URL, fetch time, rows and SHA-256

Built by `py tasks.py replays` from the committed seed (FRED, NSDL, RBI) and, for GILT2022, the
Bank of England's published nominal yield-curve archive. Nothing here is hand-edited: inputs that
were never published day by day (LDI funds' gilt sales) are written into episode.yaml as the
cited estimates they are, and the runners state how they spread them over days.
