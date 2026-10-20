import { describe, expect, it } from 'vitest';

import { type Nss, nssQuoteYield, nssZero } from './nss';

// Values from sovereign_engine.curves.nss for the same parameters.
const CURVE: Nss = { beta0: 0.07, beta1: -0.015, beta2: -0.02, beta3: 0.03, tau1: 1.5, tau2: 9 };

describe('NSS curves', () => {
  it('matches the engine’s zero rates', () => {
    expect(nssZero(CURVE, 0.25)).toBeCloseTo(0.05509982712569454, 14);
    expect(nssZero(CURVE, 10)).toBeCloseTo(0.07301813369843323, 14);
    expect(nssZero(CURVE, 30)).toBeCloseTo(0.07585871430428724, 14);
    expect(nssZero(CURVE, 0)).toBeCloseTo(0.07 - 0.015, 14);
  });

  it('matches the engine’s bill and par yields', () => {
    expect(nssQuoteYield(CURVE, 91 / 365)).toBeCloseTo(0.05547949300228428, 13);
    expect(nssQuoteYield(CURVE, 2)).toBeCloseTo(0.059598050624600434, 13);
    expect(nssQuoteYield(CURVE, 10)).toBeCloseTo(0.0726461163897644, 13);
    expect(nssQuoteYield(CURVE, 30)).toBeCloseTo(0.07551310351933235, 13);
  });
});
