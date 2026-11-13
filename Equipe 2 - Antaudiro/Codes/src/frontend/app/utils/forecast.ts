export type Level = "low" | "moderate" | "high";
export type Thresholds = { moderate: number; high: number };
export function validThresholds(moderate: number, high: number) {
  return (
    Number.isInteger(moderate) &&
    Number.isInteger(high) &&
    moderate >= 1 &&
    high > moderate &&
    high <= 2000
  );
}
export function risk(peak: number, thresholds: Thresholds): Level {
  return peak >= thresholds.high
    ? "high"
    : peak >= thresholds.moderate
      ? "moderate"
      : "low";
}
export const levelLabels: Record<Level, string> = {
  low: "Faible",
  moderate: "Modérée",
  high: "Élevée",
};
export function offsetDate(anchor: string, offset: number) {
  const date = new Date(anchor + "T12:00:00Z");
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}
export function mondayOffset(anchor: string) {
  return -((new Date(anchor + "T12:00:00Z").getUTCDay() + 6) % 7);
}
export function forecastIndex(anchor: string, date: string) {
  const index = Math.round(
    (Date.parse(date + "T12:00:00Z") - Date.parse(anchor + "T12:00:00Z")) /
      86400000,
  );
  return index >= 0 && index < 7 ? index : null;
}
export function formatDate(
  date: string,
  options: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" },
) {
  return new Intl.DateTimeFormat("fr-FR", {
    ...options,
    timeZone: "UTC",
  }).format(new Date(date + "T12:00:00Z"));
}
export function hourlyValues(peak: number, total: number) {
  const values = [
    0, 0.04, 0.2, 0.38, 0.5, 0.73, 1, 0.79, 0.47, 0.22, 0.07, 0.01,
  ].map((v) => Math.round(v * peak));
  let delta = total - values.reduce((a, b) => a + b, 0);
  const indices = [5, 7, 4, 8, 3, 9, 2, 10, 1];
  for (let i = 0; delta !== 0 && i < 10000; i++) {
    const j = indices[i % indices.length]!;
    if (delta > 0 && values[j]! < peak) {
      values[j]!++;
      delta--;
    } else if (delta < 0 && values[j]! > 0) {
      values[j]!--;
      delta++;
    }
  }
  return values;
}
