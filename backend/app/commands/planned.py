"""Functions later phases deliver; registered now so HELP and autocomplete show the whole plan."""

from app.commands.registry import planned

planned(
    "CCIL",
    "CCIL",
    "How NDS-Call, TREPS and market repo clear through CCIL",
    "IN",
    "Phase 12 (terminal completion)",
)
planned(
    "REPLAY",
    "REPLAY TAPER2013",
    "Replay a real episode against the model",
    "X",
    "Phase 11 (replays)",
)
planned("SAVE", "SAVE name", "Save the current scenario", "SYS", "Phase 13 (polish)")
planned("LOAD", "LOAD name", "Load a saved scenario", "SYS", "Phase 13 (polish)")
planned("EXPORT", "EXPORT CSV|PNG", "Export the focused panel", "SYS", "Phase 13 (polish)")
