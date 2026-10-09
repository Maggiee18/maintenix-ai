import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { HealthBadge, Pagination, ProbabilityBar, QueryState, SourceBadge } from "./ui";

const q = (over: object) => ({ data: undefined, isLoading: false, error: null, refetch: vi.fn(), ...over });

describe("QueryState", () => {
  it("renders loading, error with retry, empty and content states", async () => {
    const { rerender } = render(<QueryState q={q({ isLoading: true })}>{() => "content"}</QueryState>);
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();

    const err = q({ error: new ApiError(500, "internal_error", "Server broke") });
    rerender(<QueryState q={err}>{() => "content"}</QueryState>);
    expect(screen.getByRole("alert")).toHaveTextContent("Server broke");
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(err.refetch).toHaveBeenCalled();

    rerender(<QueryState q={q({ data: [] })} empty={(d: unknown[]) => (d.length === 0 ? "nothing here" : false)}>{() => "content"}</QueryState>);
    expect(screen.getByText("nothing here")).toBeInTheDocument();

    rerender(<QueryState q={q({ data: [1] })} empty={(d: number[]) => (d.length === 0 ? "nothing" : false)}>{(d) => `items ${d.length}`}</QueryState>);
    expect(screen.getByText("items 1")).toBeInTheDocument();
  });
});

describe("badges", () => {
  it("labels health states and simulated data explicitly", () => {
    render(<><HealthBadge state="at_risk" /><SourceBadge source="simulated" /><ProbabilityBar value={1} level="high" /></>);
    expect(screen.getByText("At risk")).toBeInTheDocument();
    expect(screen.getByText("Simulated")).toHaveAttribute("title", expect.stringMatching(/not a real machine/));
    expect(screen.getByText(">99%")).toBeInTheDocument();
  });
});

describe("Pagination", () => {
  it("disables navigation at the bounds", async () => {
    const onPage = vi.fn();
    render(<Pagination page={1} pageSize={10} total={25} onPage={onPage} />);
    expect(screen.getByText("1–10 of 25")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPage).toHaveBeenCalledWith(2);
  });
});
