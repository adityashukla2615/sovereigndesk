"""Functions later phases deliver; registered now so HELP and autocomplete show the whole plan."""

from app.commands.registry import planned

_INDIA = "Phase 6 (India simulator)"

planned("CALL", "CALL", "India call/notice/term money market: trades, high/low, WACR", "IN", _INDIA)
planned("WACR", "WACR", "Weighted average call rate inside the LAF corridor", "IN", _INDIA)
planned(
    "LAF", "LAF", "RBI liquidity adjustment facility: SDF, MSF, VRR/VRRR auctions", "IN", _INDIA
)
planned(
    "NDTL",
    "NDTL",
    "Synthetic banks: NDTL, CRR and SLR holdings",
    "IN",
    "Phase 5 (India data and banks)",
)
planned("CRR", "CRR 3.5", "Change the cash reserve ratio and see the liquidity drain", "IN", _INDIA)
planned(
    "REPO", "REPO +25BP", "Change the policy repo rate (SDF and MSF move with it)", "IN", _INDIA
)
planned("VRR", "VRR 50000CR 7D", "Variable-rate repo auction (liquidity injection)", "IN", _INDIA)
planned("VRRR", "VRRR 50000CR 7D", "Variable-rate reverse repo auction (absorption)", "IN", _INDIA)
planned("TAXCAL", "TAXCAL", "Advance-tax and GST liquidity calendar heatmap", "IN", _INDIA)
planned("CCIL", "CCIL", "How NDS-Call, TREPS and market repo clear through CCIL", "IN", _INDIA)
planned(
    "GSEC", "GSEC", "India G-sec curve (NSS) and repo pass-through", "IN", "Phase 7 (G-sec curve)"
)
planned("SPRD", "SPRD", "US 10Y vs India 10Y spread", "X", "Phase 7 (G-sec curve)")
planned(
    "MPC", "MPC", "Next MPC decision: probabilities and backtest", "IN", "Phase 8 (MPC predictor)"
)
planned("LINK", "LINK", "US → India transmission chain", "X", "Phase 9 (linkage)")
planned(
    "REPLAY",
    "REPLAY TAPER2013",
    "Replay a real episode against the model",
    "X",
    "Phase 10 (replays)",
)
planned("SAVE", "SAVE name", "Save the current scenario", "SYS", "Phase 12 (polish)")
planned("LOAD", "LOAD name", "Load a saved scenario", "SYS", "Phase 12 (polish)")
planned("EXPORT", "EXPORT CSV|PNG", "Export the focused panel", "SYS", "Phase 12 (polish)")
