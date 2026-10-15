export type DateWindows = {
  before_start: string;
  before_end: string;
  after_start: string;
  after_end: string;
};

export function shiftYear(value: string, years: number) {
  const date = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(date.getTime())) return "";
  const month = date.getUTCMonth();
  date.setUTCFullYear(date.getUTCFullYear() + years);
  if (date.getUTCMonth() !== month) date.setUTCDate(0);
  return date.toISOString().slice(0, 10);
}

export function comparisonDateError(dates: DateWindows) {
  if (!dates.before_end || !dates.after_end) return "İki tarihi de seçin.";
  if (dates.after_end < shiftYear(dates.before_end, 2))
    return "İki tarihi en az 2 yıl arayla seçin.";
  return "";
}

function shiftDay(value: string, days: number) {
  const date = new Date(`${value}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(date.getTime()))
    return "";
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function comparisonWindows(before: string, after: string): DateWindows {
  const beforeStart = shiftDay(before, -29);
  const afterStart = shiftDay(after, -29);
  // Retain the chosen endpoints. Close dates shorten the second search window
  // instead of sharing observations with the first period.
  const nextDay = before && after && before < after ? shiftDay(before, 1) : "";
  return {
    before_start: beforeStart
      ? beforeStart < "2017-01-01"
        ? "2017-01-01"
        : beforeStart
      : "",
    before_end: before,
    after_start: afterStart
      ? [afterStart, "2017-01-01", nextDay].sort().at(-1)!
      : "",
    after_end: after,
  };
}
