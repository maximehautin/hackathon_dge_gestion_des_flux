import { test } from "node:test";
import assert from "node:assert/strict";
import {
  forecastIndex,
  mondayOffset,
  offsetDate,
  risk,
  validThresholds,
  hourlyValues,
} from "../app/utils/forecast.ts";
test("week crosses the forecast boundary without extending seven-day availability", () => {
  const anchor = "2026-11-10";
  assert.equal(offsetDate(anchor, mondayOffset(anchor)), "2026-11-09");
  assert.equal(forecastIndex(anchor, "2026-11-09"), null);
  assert.equal(forecastIndex(anchor, "2026-11-16"), 6);
  assert.equal(forecastIndex(anchor, "2026-11-17"), null);
  assert.equal(offsetDate("2026-12-31", 1), "2027-01-01");
});
test("threshold boundaries and invalid draft values", () => {
  assert.equal(validThresholds(25, 25), false);
  assert.equal(validThresholds(0, 40), false);
  assert.equal(validThresholds(25, 10001), false);
  assert.equal(validThresholds(25, 40), true);
  assert.equal(risk(24, { moderate: 25, high: 40 }), "low");
  assert.equal(risk(25, { moderate: 25, high: 40 }), "moderate");
  assert.equal(risk(40, { moderate: 25, high: 40 }), "high");
});
test("illustrative hourly values retain the displayed daily total and peak", () => {
  const values = hourlyValues(31, 168);
  assert.equal(
    values.reduce((a, b) => a + b, 0),
    168,
  );
  assert.equal(Math.max(...values), 31);
});
