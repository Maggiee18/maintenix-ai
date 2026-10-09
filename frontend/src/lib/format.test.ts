import { describe, expect, it } from "vitest";
import { label, pct, prob, rulText } from "./format";

describe("formatters", () => {
  it("never shows certainty for probabilities", () => {
    expect(prob(1)).toBe(">99%");
    expect(prob(0)).toBe("<1%");
    expect(prob(0.456)).toBe("46%");
    expect(prob(null)).toBe("—");
  });
  it("describes RUL honestly", () => {
    expect(rulText(null, "unavailable")).toBe("RUL unavailable");
    expect(rulText(200, "ok", 200)).toBe("≥ 200 h");
    expect(rulText(42.4, "ok", 200)).toBe("42 h");
    expect(rulText(null, "insufficient_data")).toBe("Insufficient data");
  });
  it("formats labels and percentages", () => {
    expect(label("at_risk")).toBe("At risk");
    expect(pct(0.1234, 1)).toBe("12.3%");
  });
});

describe("rul units", () => {
  it("uses flight cycles for turbofans", () => {
    expect(rulText(30.2, "ok", 125, "cycles")).toBe("30 cycles");
    expect(rulText(125, "ok", 125, "cycles")).toBe("≥ 125 cycles");
  });
});
