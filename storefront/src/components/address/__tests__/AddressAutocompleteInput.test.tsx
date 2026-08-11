import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AddressAutocompleteInput } from "@/components/address/AddressAutocompleteInput";

// The one seam: components never touch window.google directly.
vi.mock("@/lib/googleMaps", () => ({
  mapsConfigured: vi.fn(() => true),
  fetchStreetSuggestions: vi.fn(async () => [
    { id: "p1", mainText: "12 Allen Avenue", secondaryText: "Ikeja, Lagos" },
  ]),
  resolveSuggestion: vi.fn(async () => ({
    line1: "12 Allen Avenue",
    lat: 6.60184,
    lng: 3.35149,
    lgaName: "Ikeja Local Government Area",
    stateName: "Lagos",
  })),
}));

import { fetchStreetSuggestions, mapsConfigured, resolveSuggestion } from "@/lib/googleMaps";

function setup(overrides: Partial<Parameters<typeof AddressAutocompleteInput>[0]> = {}) {
  const onChangeText = vi.fn();
  const onPick = vi.fn();
  render(
    <AddressAutocompleteInput
      id="line1"
      value=""
      onChangeText={onChangeText}
      onPick={onPick}
      {...overrides}
    />,
  );
  return { onChangeText, onPick };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

describe("AddressAutocompleteInput", () => {
  it("debounces typing, shows suggestions, and resolves a pick", async () => {
    const { onChangeText, onPick } = setup();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "12 Allen" } });
    expect(onChangeText).toHaveBeenCalledWith("12 Allen"); // free text flows regardless

    await vi.advanceTimersByTimeAsync(300);
    const option = await screen.findByText("12 Allen Avenue");
    expect(fetchStreetSuggestions).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/powered by Google/i)).toBeInTheDocument();

    fireEvent.click(option);
    await waitFor(() => expect(onPick).toHaveBeenCalled());
    expect(resolveSuggestion).toHaveBeenCalledWith("p1", "12 Allen Avenue");
    expect(onPick.mock.calls[0][0]).toMatchObject({ lat: 6.60184, lng: 3.35149 });
    expect(onChangeText).toHaveBeenLastCalledWith("12 Allen Avenue");
  });

  it("keyboard: arrow down + Enter picks without submitting the form", async () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    const onPick = vi.fn();
    render(
      <form onSubmit={onSubmit}>
        <AddressAutocompleteInput id="l1" value="" onChangeText={vi.fn()} onPick={onPick} />
      </form>,
    );
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "12 Allen" } });
    await vi.advanceTimersByTimeAsync(300);
    await screen.findByText("12 Allen Avenue");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(onPick).toHaveBeenCalled());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("is a plain input when maps are not configured — assist, never a gate", async () => {
    vi.mocked(mapsConfigured).mockReturnValue(false);
    const { onChangeText } = setup();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "5 My Street" } });
    expect(onChangeText).toHaveBeenCalledWith("5 My Street");
    await vi.advanceTimersByTimeAsync(500);
    expect(fetchStreetSuggestions).not.toHaveBeenCalled();
  });

  it("shows nothing when the fetch returns no suggestions", async () => {
    vi.mocked(fetchStreetSuggestions).mockResolvedValue([]);
    setup();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "unmapped road" } });
    await vi.advanceTimersByTimeAsync(300);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
