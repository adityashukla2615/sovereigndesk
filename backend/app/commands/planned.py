"""Functions later phases deliver; registered now so HELP and autocomplete show the whole plan."""

from app.commands.registry import planned

planned("SAVE", "SAVE name", "Save the current scenario", "SYS", "Phase 13 (polish)")
planned("LOAD", "LOAD name", "Load a saved scenario", "SYS", "Phase 13 (polish)")
planned("EXPORT", "EXPORT CSV|PNG", "Export the focused panel", "SYS", "Phase 13 (polish)")
