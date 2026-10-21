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
  GSEC:
    'India’s government bond curve: the 91, 182 and 364-day T-bills, then G-secs out to 30 years ' +
    'at FBIL’s par yields, fitted with Nelson–Siegel–Svensson. A repo surprise moves the short ' +
    'end almost one for one and the long end less. How much is measured on RBI’s repo changes ' +
    'since 2022: on the day yields moved only a fraction of each change, because most were ' +
    'expected, so each maturity is scaled by the 3-month yield’s move, the surprise. The fit ' +
    'splits β into expectations (the market expects a surprise to fade; the half-life is about a ' +
    'year) and a term premium that does not fade with maturity. Eleven events: the bands are wide.',
  SPRD:
    'India’s 10-year yield sits a little over two points above the US 10-year: higher inflation ' +
    'and growth, a rupee expected to weaken, and liquidity and credit premia. When US yields rise ' +
    'faster than India’s, the spread narrows and Indian bonds pay foreign investors less for ' +
    'those risks: the first link in the US → India chain (LINK, Phase 9).',
  MPC:
    'The forecast for RBI’s next decision, from what was public the day before: CPI and core ' +
    'inflation (MoSPI), GDP growth, WACR and T-bills against repo, system liquidity, the Fed ' +
    'funds rate, the rupee, and the previous move. Three models: a Taylor rule (inflation and ' +
    'output gaps; moves part of the way, in 25 bp steps), an ordered logit, and boosted trees. ' +
    'The backtest refits each model on earlier decisions only and scores the next one, against ' +
    'repeating the last decision and always holding. Holds dominate the sample, so a high hit ' +
    'rate alone says little: macro-F1 and the Brier score reward getting the moves right.',
  REPLAY:
    'A replay drives the model with what actually moved in a real episode (the US 10Y in 2013, ' +
    'the Fed’s purchases in 2020, LDI funds’ forced sales in 2022) and sets each of its paths ' +
    'against what actually happened. The scores say how close it came (typical error), whether ' +
    'it moved the right way week by week, and how big and how late its peak was. Where the ' +
    'inputs were never published day by day the episode says so, and shows how much the answer ' +
    'depends on the assumption.',
  IMPACT:
    'What the simulated moves mean for people. A bond loses value when yields rise: by about ' +
    'its modified duration times the rise, a little less because of convexity, and exactly what ' +
    'repricing its cash flows says. Held to maturity it still pays every coupon and its face ' +
    'value, so the loss is only crystallised by selling. A business with a floating-rate loan ' +
    'pays more once the loan resets: an EBLR loan takes a repo move in full, an MCLR loan only ' +
    'part of it and slowly (fitted on RBI’s monthly data). An importer also pays more for its ' +
    'stock when the rupee weakens, passes some of it to prices and sells less. The portfolio ' +
    'and the businesses are illustrative: edit them to your own.',
  LINK:
    'How a US shock reaches India’s money market. A Fed hike lifts the US 10-year; India’s ' +
    '10-year follows only partly, so the yield gap narrows and foreign portfolio money leaves ' +
    'over the following weeks. RBI sells dollars from its reserves to steady the rupee, and ' +
    'every dollar it sells takes rupees out of the banks: liquidity tightens and WACR and ' +
    'T-bills rise. RBI can let that happen, fund the shortfall with VRR auctions (the deficit ' +
    'is then met at the repo rate, but the net position does not change), restore it with OMO ' +
    'purchases or a buy/sell swap, or hike repo. Each link is a regression on public data, ' +
    'with its 90% interval in the table.',
  UST:
    'The Treasury par curve: the yield at which a new Treasury of each maturity would price at ' +
    'par. Policy moves shift the front end most; term-premium shocks and foreign selling move the ' +
    'long end. A big holder’s sale pushes yields up while it lasts (temporary impact) and leaves a ' +
    'permanent part, scaled to the size of the market.',
};
