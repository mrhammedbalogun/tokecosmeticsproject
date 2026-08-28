import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { LandmarkField } from "@/components/address/LandmarkField";
import { needsLandmark } from "@/components/checkout/address-fields";

describe("needsLandmark", () => {
  it("asks Nigeria and nobody else", () => {
    // Mirrors apps.core.address_rules._LANDMARK_COUNTRIES. If these two ever disagree
    // the shopper gets a required field they were never shown, or a shown field the
    // server does not want — so this is pinned on both sides.
    expect(needsLandmark("NG")).toBe(true);
    expect(needsLandmark("ng")).toBe(true);
    for (const code of ["GB", "US", "CA", "ZZ", "FR", ""]) {
      expect(needsLandmark(code)).toBe(false);
    }
  });
});

describe("LandmarkField", () => {
  function setup(props: Partial<React.ComponentProps<typeof LandmarkField>> = {}) {
    const onChange = vi.fn();
    render(
      <LandmarkField idPrefix="addr" value="" onChange={onChange} {...props} />,
    );
    return { onChange };
  }

  it("renders a required input the shopper can type into", () => {
    const { onChange } = setup();

    const input = screen.getByLabelText("Landmark");
    expect(input).toBeRequired();

    fireEvent.change(input, { target: { value: "Opposite Ikeja City Mall" } });
    expect(onChange).toHaveBeenCalledWith("Opposite Ikeja City Mall");
  });

  it("namespaces its id, since checkout and the account form can both be mounted", () => {
    setup({ idPrefix: "addr-form" });
    expect(screen.getByLabelText("Landmark")).toHaveAttribute("id", "addr-form-landmark");
  });

  it("keeps the explanation hidden until the ? is pressed", () => {
    setup();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "What is a landmark?" }));

    // The popup has to answer "what do you want from me", so it names concrete kinds
    // of place rather than defining the word.
    const help = screen.getByRole("dialog");
    expect(help).toHaveTextContent(/bus stop/i);
    expect(help).toHaveTextContent(/mall/i);
  });

  it("is a real popover, not a title tooltip — it closes on Escape", () => {
    // `title=` never appears on touch, and most of this shop's traffic is phones. That
    // makes dismissal a real requirement: a popup you can only close by finding the
    // same 16px button again is worse than none.
    setup();
    fireEvent.click(screen.getByRole("button", { name: "What is a landmark?" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes on an outside click too", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "What is a landmark?" }));

    fireEvent.mouseDown(document.body);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the server's field error against the field itself", () => {
    setup({ errors: ["This field is required for this country."] });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "This field is required for this country.",
    );
  });

  it("caps the input at the column width so a save cannot 400 on length", () => {
    setup();
    expect(screen.getByLabelText("Landmark")).toHaveAttribute("maxLength", "120");
  });
});
