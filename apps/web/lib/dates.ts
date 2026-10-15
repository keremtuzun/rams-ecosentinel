export type DateWindows = {
  before_start: string;
  before_end: string;
  after_start: string;
  after_end: string;
};

function validDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return (
    Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
  );
}

export const todayUTC = () => new Date().toISOString().slice(0, 10);

export function shiftYear(value: string, years: number) {
  if (!validDate(value)) return "";
  const date = new Date(`${value}T00:00:00Z`);
  const month = date.getUTCMonth();
  date.setUTCFullYear(date.getUTCFullYear() + years);
  if (date.getUTCMonth() !== month) date.setUTCDate(0);
  return date.toISOString().slice(0, 10);
}

export function comparisonDateError(dates: DateWindows, today = todayUTC()) {
  if (!Object.values(dates).every(validDate))
    return "Dört tarih alanını da geçerli tarihlerle doldurun.";
  for (const [start, end] of [
    [dates.before_start, dates.before_end],
    [dates.after_start, dates.after_end],
  ]) {
    if (start < "2017-01-01" || start > end || end > today)
      return "2017 veya sonrasından, bugünü (UTC) aşmayan tarihler seçin. Başlangıç bitişten sonra olamaz.";
    if (dayDifference(start, end) > 62)
      return "Her görüntü arama aralığı en fazla 62 gün olabilir.";
  }
  if (dates.before_end >= dates.after_start)
    return "Tarih aralıkları çakışıyor. Sonraki dönem önceki dönemden sonra başlamalı.";
  if (dates.after_end < shiftYear(dates.before_end, 2))
    return "İki tarihi en az 2 yıl arayla seçin.";
  if (dayDifference(dates.before_start, dates.after_end) > 3653)
    return "İki dönem arasındaki fark en fazla 10 yıl olabilir.";
  // Match the server's actual-year ordinal rule, including leap years.
  const ordinal = (value: string) =>
    dayDifference(`${value.slice(0, 4)}-01-01`, value) + 1;
  const delta = Math.abs(
    ordinal(dates.before_start) - ordinal(dates.after_start),
  );
  if (Math.min(delta, 366 - delta) > 45)
    return "Aynı mevsimden iki tarih seçin (en fazla 45 gün mevsim farkı).";
  return "";
}

function dayDifference(start: string, end: string) {
  return (
    (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) /
    86400000
  );
}

function shiftDay(value: string, days: number) {
  if (!validDate(value)) return "";
  const date = new Date(`${value}T00:00:00Z`);
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
