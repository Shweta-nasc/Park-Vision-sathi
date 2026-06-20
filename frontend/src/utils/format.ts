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
