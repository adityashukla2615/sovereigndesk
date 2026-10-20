/** Teach-mode notes: the economics behind each panel, shown when TEACH is on. */

export const TEACH: Record<string, string> = {
  PY:
    'A bond’s price falls as its yield rises, but along a curve, not a line. Modified duration ' +
    'is the slope: the per cent price change for a one-point move in yield. Convexity is the ' +
    'curvature: it makes the price fall less, and rise more, than duration alone predicts. So the ' +
    'duration-only line (blue) understates the price for big moves either way, while duration ' +
    'plus convexity (green) hugs the exact price (amber). DV01 is the price change per basis point.',
  FED:
    'The Fed sets a target range and administers rates inside it: interest on reserve balances ' +
    '(IORB), the ON RRP rate near the bottom and the standing repo facility at the top. EFFR ' +
    'settles where banks’ demand for reserves meets supply. With reserves abundant the demand ' +
    'curve is flat and EFFR sits a few basis points below IORB; as QT drains reserves (ON RRP ' +
    'first) the curve steepens and EFFR rises toward IORB and above, as in September 2019. The ' +
    'curve is fitted to weekly data since 2017; a QT plan shows its path month by month.',
  WACR:
    'RBI targets the weighted average call rate (WACR) and keeps it near the repo rate inside a ' +
    'corridor: the SDF is the floor (banks park surplus with RBI) and the MSF the ceiling (banks ' +
    'borrow against SLR securities). When the system has surplus, lenders compete and WACR sinks ' +
    'toward the SDF; in deficit it rises toward the MSF. The macro map is fitted on RBI’s daily ' +
    'releases since April 2022. Advance tax (mid-quarter) and GST (the 20th) drain liquidity, and ' +
    'RBI answers with VRR and VRRR auctions. The 40 banks are SYNTHETIC; their total NDTL is real.',
  UST:
    'The Treasury par curve: the yield at which a new Treasury of each maturity would price at ' +
    'par. Policy moves shift the front end most; term-premium shocks and foreign selling move the ' +
    'long end. A big holder’s sale pushes yields up while it lasts (temporary impact) and leaves a ' +
    'permanent part, scaled to the size of the market.',
};
