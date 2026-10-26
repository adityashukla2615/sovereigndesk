# SovereignDesk: a three-minute demo

Seven beats, about 25 seconds each, from a bond's price to RBI's next decision. Each beat lists what to type, where to look and what to say. The numbers below come from the committed seed (US data to 16 Oct 2026, RBI's to 19 Oct) with the simulator's seed fixed at 7. Typed at a different moment, they move by a basis point or two. `py tasks.py demo` runs every command typed below on the seed and checks that it answers.

## Before you start

```sh
py tasks.py setup                       # once
$env:SD_SIM_SEED = "7"                  # PowerShell; `export SD_SIM_SEED=7` elsewhere
py tasks.py dev --offline               # the seed only: no network needed
```

Open http://localhost:5173. The terminal opens on four panels: PY (price–yield), FED, WACR and UST. If it reopens on an old layout, type `LAYOUT DEFAULT` and then `RESET`. Press `Alt+T` at any point for teach mode: every panel explains its own economics.

**Opening line (10 s).** "This is a Bloomberg-style terminal that simulates the US Treasury market and India's money market, each anchored to real data: FRED, the Treasury, TIC, RBI, FBIL, NSDL and MoSPI. Every number on screen is either real data with its date or a model I can explain."

## 1. Price and yield (25 s)

Type: `PY 10Y`

Look at panel 1: the exact price curve (amber), the duration line (blue) and duration plus convexity (green).

"A 10-year Treasury at par yields 5.09%. Its modified duration is 7.76: a 1-point rise in yield costs about 7.8% of the price. The duration line is straight, but the price curve bends. That is convexity, 73 here: it is why the straight line understates the price for big moves both ways, while duration plus convexity sits on the exact curve."

## 2. The Fed runs down its balance sheet (25 s)

Type: `QT 95B`

Look at panel 2 (FED): reserves against the fitted demand curve, and the 24-month QT path.

"The Fed lets $95 billion a month run off: $60 billion of Treasuries and $35 billion of MBS. Over two years reserves fall by $2.3 trillion to about $740 billion, 2.8% of bank assets. That is past the flat part of the demand curve, fitted on weekly data since 2017, so the fed funds rate starts to climb toward interest on reserves, as it did in September 2019. The 10-year term premium rises about 26 bp."

## 3. Japan sells (25 s)

Type: `SHOCK JP 200B 10D LONG`

Look at panel 4 (UST): the live curve against today's close and the shock's long-run shape. Then look at the event log.

"Japan, the largest foreign holder in TIC's data, sells $200 billion of long Treasuries over ten days. While it sells, the 30-year rises about 7 bp and the 10-year 3 bp; most of that fades and a small permanent part stays. The price impact comes from Beltran et al., scaled to today's much larger market. The gilt crisis replay checks it independently. The log turns it into the interest bill, about $0.4 billion a year after one year."

## 4. From the Fed to India's call money (25 s)

Type: `SHOCK FED 50BP`, then `LINK`

Look at the LINK panel: each node of the chain, with the 90% interval of every link in the table.

"A 50 bp Fed hike lifts the US 10-year by about 12 bp. India's 10-year follows only partly, so the yield gap narrows by about 10 bp. Foreign portfolio money leaves, about half a billion dollars over a month, and RBI sells dollars to steady the rupee. Every dollar it sells takes rupees out of the banks, so liquidity tightens a little. Each link is a regression on public data: NSDL's flows, RBI's reserves, FRED. RBI can answer with VRRs, OMOs, a swap or a hike: `SHOCK FED 50BP VRR` shows the difference."

## 5. The 2013 taper tantrum, replayed (25 s)

Type: `REPLAY TAPER2013`

Look at the REPLAY panel: press PLAY, then point at the scores and the summary.

"Now a real episode. The chain was calibrated on 2014 to 2026, and here it is driven by what actually happened to US yields in 2013, so this is out of sample. It gets the direction of foreign flows right in 71% of the weeks that moved. The peak outflow is too small, $5.5 billion against $8 billion. It misses the rupee's fall almost entirely: 2013's pressure came from outside this chain. The replay says where the model is wrong as plainly as where it is right."

## 6. India's advance-tax squeeze (25 s)

Type: `TAXCAL`, then `REPLAY ADVTAX`

Look at the TAXCAL calendar of WACR − repo, then the chart of the government's tax balance against the system's surplus.

"Four times a year, around the 15th of March, June, September and December, companies pay advance tax. RBI's data puts the median at ₹1.28 lakh crore leaving the banks for the government's account, plus GST around every 20th. The calendar shows the squeezes: red is the call rate above repo. Ahead, the system dips into deficit around 22 December, which makes an RBI VRR more likely. The replay runs the liquidity map on the three worst real squeezes since 2022, against what WACR actually did."

## 7. RBI's next decision (25 s)

Type: `MPC`

Look at the MPC panel: the probabilities for the next meeting, and the backtest table.

"The next MPC meeting is on 4 December. The ordered logit gives a hold 82%. Three models are shown: a Taylor rule, the ordered logit and boosted trees, each trained only on decisions before the one it forecasts. On 54 decisions since 2018 the logit got 57% right, against 69% for simply repeating the last decision. That is the honest result: holds dominate, so the model's value is in the probabilities, not the hit rate."

**Closing line (10 s).** "Everything here is a scenario I can save and replay exactly: `SAVE DEMO`. `EXPORT PNG` saves a panel's chart, `EXPORT CSV` its data, and `ASSUMPTIONS.md` lists every source, fit and assumption, with the data's dates."

Type: `SAVE DEMO`, `EXPORT CSV`
