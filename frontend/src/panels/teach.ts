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
  CALL:
    'Banks lend each other overnight in the call market, unsecured. Every quarter hour the ' +
    'orders clear at one rate: no lender takes less than the SDF pays, and no borrower pays more ' +
    'than the MSF charges while it has SLR securities to pledge. WACR, the volume-weighted ' +
    'average of the day, is RBI’s operating target. TREPS and market repo are secured by ' +
    'government securities, so they trade a little below call; T-bills sit near repo. Each rate ' +
    'above repo signals tight liquidity, below it surplus. Small finance banks may borrow at most ' +
    '100% of capital funds on average over the fortnight (125% on any day); other banks borrow ' +
    'within limits their boards set (assumed the same here): the trimmed orders show where a ' +
    'limit binds.',
  LAF:
    'The liquidity adjustment facility is how RBI keeps the call rate near repo. Banks with ' +
    'surplus cash park it overnight at the SDF (repo − 25 bp), and banks short of it borrow at ' +
    'the MSF (repo + 25 bp) against their SLR securities; both windows open as the call market ' +
    'closes at 7 PM. Between them RBI fine-tunes with auctions: a VRR lends to the banks ' +
    '(injects), a VRRR borrows from them (absorbs), at the rates the bids set. The net position ' +
    'as a share of NDTL is the surplus that moves WACR along the macro map, and RBI’s fitted ' +
    'reaction makes a VRR likelier the tighter it gets.',
  NDTL:
    'A bank’s net demand and time liabilities (its deposits, less what it owes other banks) ' +
    'set its reserve requirements. It must hold the CRR in cash with RBI, on average over each ' +
    'reporting fortnight and above a daily floor, and the SLR in government securities. A CRR ' +
    'cut frees cash and adds system liquidity; a hike drains it. Securities above the SLR can ' +
    'be pledged at the MSF, plus a 2% dip below it. The 40 banks here are SYNTHETIC: generated, ' +
    'with India’s real total NDTL split between them.',
  TAXCAL:
    'Around the 15th of March, June, September and December companies pay advance tax, and GST ' +
    'falls due around the 20th of each month. The money leaves bank deposits for the ' +
    'government’s account at RBI, so the banks’ reserves fall rupee for rupee and the call rate ' +
    'rises toward or above repo. The government spends it back over the following weeks. RBI ' +
    'answers the squeeze with VRR auctions, more likely the tighter liquidity gets. The calendar ' +
    'shows the cycle in RBI’s own data; the chart runs it ahead from tax flows alone.',
  CCIL:
    'Three overnight markets, three kinds of plumbing. Call money is dealt on NDS-CALL, RBI’s ' +
    'platform run by Clearcorp, and settles bank to bank in RBI’s RTGS: unsecured, so each ' +
    'lender carries its borrower’s credit risk, and only banks and primary dealers may take ' +
    'part. TREPS (tri-party repo) and market repo (CROMS) are secured by government securities ' +
    'and cleared by CCIL as central counterparty: each trade is novated to CCIL, which nets ' +
    'every member’s funds and securities and guarantees settlement, so a default hits CCIL’s ' +
    'margins and default fund, not the other side of the trade.',
  DEBT:
    'The federal interest bill reprices as Treasuries mature and are refinanced, and as new ' +
    'deficits are funded, at the yields of the day. A higher curve costs little in the first ' +
    'months, because most debt was issued earlier at fixed coupons, and more each year as it ' +
    'rolls over: bills within months, ten-year notes over a decade. The comparison holds each ' +
    'curve flat, on the real maturity profile (MSPD), deficit and issuance mix.',
  TIC:
    'The Treasury’s TIC data count foreign holdings by country. Japan and China are among the ' +
    'largest holders; the UK, Luxembourg, Belgium and the Cayman Islands rank high as custody ' +
    'and fund centres, because TIC counts securities where they are held, not always by who ' +
    'owns them. A holder’s sale raises yields while it lasts and leaves a smaller permanent ' +
    'effect, scaled to the size of the market.',
  CORR:
    'Both central banks steer an overnight rate inside a corridor. The Fed pays interest on ' +
    'reserves (IORB) and takes cash at the ON RRP near the bottom of its target range, so the ' +
    'fed funds rate trades a little below IORB while reserves are abundant. RBI’s corridor sits ' +
    'around a single repo rate, the SDF 25 bp below and the MSF 25 bp above, so it is twice as ' +
    'wide as the Fed’s range. The gap between the two policy rates is one reason money moves ' +
    'between the markets.',
  HELP:
    'Every function has a code, as on a Bloomberg terminal: type it in the command bar, or ' +
    'click one here to see what it does. US codes drive the Treasury simulator, IN codes the ' +
    'Indian money market, X codes link the two; SYS codes run the terminal itself.',
  UST:
    'The Treasury par curve: the yield at which a new Treasury of each maturity would price at ' +
    'par. Policy moves shift the front end most; term-premium shocks and foreign selling move the ' +
    'long end. A big holder’s sale pushes yields up while it lasts (temporary impact) and leaves a ' +
    'permanent part, scaled to the size of the market.',
};
