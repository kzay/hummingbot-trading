import { describe, expect, it } from "vitest";

import { formatNumber, formatSigned, formatPct, formatAgeMs, toNum, normalizeSide } from "./format";

describe("toNum", () => {
  it("converts valid numbers", () => {
    expect(toNum(42)).toBe(42);
    expect(toNum("3.14")).toBe(3.14);
    expect(toNum(0)).toBe(0);
    expect(toNum("-7")).toBe(-7);
  });

  it("returns null for non-finite values", () => {
    expect(toNum(undefined)).toBeNull();
    expect(toNum(null)).toBeNull();
    expect(toNum("")).toBeNull();
    expect(toNum("abc")).toBeNull();
    expect(toNum(NaN)).toBeNull();
    expect(toNum(Infinity)).toBeNull();
    expect(toNum(-Infinity)).toBeNull();
  });

  it("handles negative zero as zero", () => {
    expect(toNum(-0)).toBe(-0);
    expect(Number.isFinite(toNum(-0))).toBe(true);
  });
});

describe("formatNumber", () => {
  it("formats valid numbers with default digits", () => {
    expect(formatNumber(1234.567)).toBe(new Intl.NumberFormat(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(1234.567));
  });

  it("formats with custom digit count", () => {
    const result = formatNumber(1.123456, 4);
    expect(result).toContain("1.1235");
  });

  it("returns n/a for non-finite inputs", () => {
    expect(formatNumber(NaN)).toBe("n/a");
    expect(formatNumber(Infinity)).toBe("n/a");
    expect(formatNumber(-Infinity)).toBe("n/a");
    expect(formatNumber("abc")).toBe("n/a");
  });

  it("coerces null to 0", () => {
    expect(formatNumber(null)).toBe("0");
  });

  it("formats string numbers", () => {
    expect(formatNumber("42.5")).not.toBe("n/a");
  });

  it("formats zero", () => {
    expect(formatNumber(0)).toBe("0");
  });
});

describe("formatSigned", () => {
  it("adds + prefix for positive numbers", () => {
    expect(formatSigned(5.5, 2)).toMatch(/^\+/);
  });

  it("adds - prefix for negative numbers", () => {
    expect(formatSigned(-3.2, 2)).toMatch(/^-/);
  });

  it("no sign prefix for zero", () => {
    const result = formatSigned(0, 2);
    expect(result).not.toMatch(/^[+-]/);
    expect(result).toBe("0");
  });

  it("returns n/a for non-finite inputs", () => {
    expect(formatSigned(NaN)).toBe("n/a");
    expect(formatSigned(Infinity)).toBe("n/a");
  });

  it("coerces null to 0", () => {
    expect(formatSigned(null)).toBe("0");
  });
});

describe("formatPct", () => {
  it("formats as percentage", () => {
    expect(formatPct(0.1234)).toBe("12.34%");
    expect(formatPct(1)).toBe("100.00%");
    expect(formatPct(0)).toBe("0.00%");
  });

  it("respects custom digits", () => {
    expect(formatPct(0.12345, 3)).toBe("12.345%");
  });

  it("returns n/a for non-finite inputs", () => {
    expect(formatPct(NaN)).toBe("n/a");
    expect(formatPct(Infinity)).toBe("n/a");
  });

  it("coerces null to 0%", () => {
    expect(formatPct(null)).toBe("0.00%");
  });
});

describe("formatAgeMs", () => {
  it("formats milliseconds", () => {
    expect(formatAgeMs(500)).toBe("500 ms");
  });

  it("formats seconds", () => {
    expect(formatAgeMs(5_000)).toBe("5.0 s");
  });

  it("formats minutes", () => {
    expect(formatAgeMs(120_000)).toBe("2.0 m");
  });

  it("formats hours", () => {
    expect(formatAgeMs(7_200_000)).toBe("2.0 h");
  });

  it("returns n/a for null/undefined/empty/negative", () => {
    expect(formatAgeMs(null)).toBe("n/a");
    expect(formatAgeMs(undefined)).toBe("n/a");
    expect(formatAgeMs("")).toBe("n/a");
    expect(formatAgeMs(-1)).toBe("n/a");
  });

  it("handles zero", () => {
    expect(formatAgeMs(0)).toBe("0 ms");
  });
});

describe("normalizeSide", () => {
  it("lowercases and trims", () => {
    expect(normalizeSide("BUY")).toBe("buy");
    expect(normalizeSide("  Sell  ")).toBe("sell");
  });

  it("handles null/undefined", () => {
    expect(normalizeSide(null)).toBe("");
    expect(normalizeSide(undefined)).toBe("");
  });
});
