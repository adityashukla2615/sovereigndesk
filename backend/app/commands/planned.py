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
    "GSEC", "GSEC", "India G-sec curve (NSS) and repo pass-through", "IN", "Phase 7 (G-sec curve)"
)
planned("SPRD", "SPRD", "US 10Y vs India 10Y spread", "X", "Phase 7 (G-sec curve)")
planned(
    "MPC", "MPC", "Next MPC decision: probabilities and backtest", "IN", "Phase 8 (MPC predictor)"
)
planned("LINK", "LINK", "US → India transmission chain", "X", "Phase 9 (linkage)")
planned(
    "IMPACT",
    "IMPACT [RETAIL|BUSINESS profile]",
    "What a shock means for a bond portfolio and for a small business",
    "X",
    "Phase 10 (retail and business impact)",
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
