import { describe, expect, it, vi } from "vitest";
import { ApiError, api, buildUrl, errorMessage } from "./client";
import { json } from "../test/utils";

describe("api client", () => {
  it("builds query strings and skips empty values", () => {
    expect(buildUrl("/x", { a: 1, b: "", c: undefined, d: ["p", "q"] })).toBe("/api/v1/x?a=1&d=p&d=q");
  });
  it("sends the bearer token and parses the error envelope", async () => {
    sessionStorage.setItem("mx-token", "abc");
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json({ error: { code: "validation_failed", message: "Readings rejected", details: { errors: [{ message: "vibration out of range" }] }, request_id: "r1" } }, 422));
    const err = (await api.get("/equipment").catch((e) => e)) as ApiError;
    expect((spy.mock.calls[0][1]?.headers as Record<string, string>).Authorization).toBe("Bearer abc");
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(errorMessage(err)).toBe("Readings rejected: vibration out of range");
  });
  it("reports network failures", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("fail"));
    const err = (await api.get("/x").catch((e) => e)) as ApiError;
    expect(err.code).toBe("network_error");
  });
});
