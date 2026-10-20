/**
 * Nelson–Siegel–Svensson curves from the parameters the backend publishes, so a panel can draw
 * the live fitted curve without the backend sending it point by point. Mirrors
 * engine/src/sovereign_engine/curves/nss.py: zero rates are continuously compounded decimals.
 */

export interface Nss {
  beta0: number;
  beta1: number;
  beta2: number;
  beta3: number;
  tau1: number;
  tau2: number;
}

/** (1 − e^(−x)) / x, one at zero. */
function level(x: number): number {
  return x > 0 ? -Math.expm1(-x) / x : 1;
}

/** Continuously compounded zero rate at `years`. */
export function nssZero(c: Nss, years: number): number {
  const x1 = years / c.tau1;
  const x2 = years / c.tau2;
  const l1 = level(x1);
  return (
    c.beta0 + c.beta1 * l1 + c.beta2 * (l1 - Math.exp(-x1)) + c.beta3 * (level(x2) - Math.exp(-x2))
  );
}

export function nssDiscount(c: Nss, years: number): number {
  return Math.exp(-nssZero(c, years) * years);
}

/**
 * The yield a quote of this maturity has on the curve: a bill's simple yield below one year,
 * else the coupon of a par bond paying `freq` coupons a year (whole coupon periods only).
 */
export function nssQuoteYield(c: Nss, years: number, freq = 2): number {
  if (years < 1) return (1 / nssDiscount(c, years) - 1) / years;
  const periods = Math.round(years * freq);
  let annuity = 0;
  for (let k = 1; k <= periods; k += 1) annuity += nssDiscount(c, k / freq);
  return (freq * (1 - nssDiscount(c, periods / freq))) / annuity;
}
