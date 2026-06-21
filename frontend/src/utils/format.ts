export const hourLabel = (h: number): string =>
  h === 0 ? '12 AM' : h < 12 ? `${h} AM` : h === 12 ? '12 PM' : `${h - 12} PM`;

export const isPeak = (h: number): boolean => (h >= 8 && h <= 10) || (h >= 17 && h <= 19);

export const timePeriod = (h: number): string => {
  if (h >= 8 && h <= 10) return 'Morning Peak';
  if (h >= 17 && h <= 19) return 'Evening Peak';
  if (h >= 6 && h < 8) return 'Early Morning';
  if (h >= 11 && h <= 16) return 'Midday';
  if (h >= 20 && h <= 22) return 'Late Evening';
  return 'Night';
};

export const cleanJunction = (name?: string | null): string =>
  name && name !== 'No Junction' ? name.replace(/^BTP\d+\s*-\s*/, '') : '';

export const fmt = (n: number, d = 0): string =>
  n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

/** A short, distinctive suffix of an H3 id (e.g. 8960145b553ffff → "b553"). */
export const shortId = (h3?: string | null): string => {
  if (!h3) return '—';
  const core = h3.replace(/f+$/i, '');
  return core.slice(-4) || h3.slice(-4);
};

/** Human-readable label for a zone: junction/locality → station → short id. */
export const zoneLabel = (z?: {
  junction?: string | null;
  top_junction?: string | null;
  station?: string | null;
  h3_id?: string;
}): string => {
  if (!z) return '—';
  const j = cleanJunction(z.junction ?? z.top_junction);
  if (j) return j;
  if (z.station) return z.station;
  return shortId(z.h3_id);
};

