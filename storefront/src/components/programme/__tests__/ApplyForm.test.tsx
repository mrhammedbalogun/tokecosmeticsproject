/**
 * The form's three states and its one invisible field.
 *
 * Not a test of the happy submit — that path is Django's, and `lib/entrepreneurship`'s
 * own tests cover the wire. These pin the things a redesign would quietly break.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApplyForm } from "@/components/programme/ApplyForm";
import { ApplyError } from "@/lib/entrepreneurship";

vi.mock("@/lib/entrepreneurship", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/entrepreneurship")>();
  return { ...actual, submitApplication: vi.fn() };
});
vi.mock("@/components/auth/TurnstileWidget", () => ({
  TurnstileWidget: () => null,
  turnstileToken: () => "test-token",
}));

import { submitApplication } from "@/lib/entrepreneurship";

const mockSubmit = vi.mocked(submitApplication);

const CONFIG = {
  is_open: true,
  closed_message: "Back in January.",
  countries: [
    { code: "NG", name: "Nigeria" },
    { code: "GB", name: "United Kingdom" },
  ],
};

/** `fireEvent`, not `user-event`: this project does not carry that dependency, and the
 *  careers form's tests next door drive their form the same way. */
function fill(label: RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function fillRequired() {
  fill(/full name/i, "Chidinma Eze");
  fill(/email address/i, "chidinma@example.com");
  fill(/university \/ polytechnic \/ college/i, "University of Lagos");
  fill(/current academic level/i, "300 Level");
  fill(/course of study/i, "Biochemistry");
  // The visible phone input carries no `name`; PhoneField submits E.164 through a
  // hidden one, which is why the value here is the national form.
  fill(/phone number/i, "8023900964");
}

/** Submits the FORM rather than clicking the button, so the browser's own `required`
 *  validation (which jsdom does not run) cannot silently swallow the submit. */
function submit() {
  fireEvent.submit(
    screen.getByRole("button", { name: /apply to the programme/i }).closest("form")!,
  );
}

describe("the application form", () => {
  it("carries a honeypot that no human can see or tab to", () => {
    // Its whole value is that a bot fills it and is then answered 201 and stored
    // nowhere. A redesign that drops the field, or makes it focusable, removes the
    // control without removing anything visible — so it is pinned here.
    const { container } = render(<ApplyForm config={CONFIG} />);
    const honeypot = container.querySelector('input[name="website"]');

    expect(honeypot).toBeTruthy();
    expect(honeypot).toHaveAttribute("tabindex", "-1");
    expect(honeypot!.closest("[aria-hidden]")).toBeTruthy();
  });

  it("offers only the markets the API named", () => {
    render(<ApplyForm config={CONFIG} />);
    const select = screen.getByLabelText(/country you study in/i) as HTMLSelectElement;

    expect([...select.options].map((o) => o.value)).toEqual(["NG", "GB"]);
  });

  it("suggests academic levels without refusing anything else", () => {
    // A `<datalist>` and not a `<select>`: "Year 2" and "Sophomore" are real answers
    // from the other markets, and refusing a real student on a marketing form is the
    // expensive error.
    render(<ApplyForm config={CONFIG} />);
    const level = screen.getByLabelText(/current academic level/i);

    expect(level).toHaveAttribute("list");
    fireEvent.change(level, { target: { value: "Sophomore" } });
    expect(level).toHaveValue("Sophomore");
  });

  it("renders a 409 as the intake closing, not as a field error", async () => {
    // Nothing the student typed is wrong, so "check the highlighted fields" would send
    // them hunting for a mistake that does not exist.
    mockSubmit.mockRejectedValueOnce(
      new ApplyError("Applications reopen in January.", {}, true),
    );
    render(<ApplyForm config={CONFIG} />);
    fillRequired();
    submit();

    await waitFor(() => {
      expect(screen.getByText(/applications just closed/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/were not submitted/i)).toBeInTheDocument();
  });

  it("keeps what was typed when a field is refused", async () => {
    // The failure a student will actually hit is the phone rule, and a nine-field form
    // that empties itself over one field is a form that gets abandoned.
    mockSubmit.mockRejectedValueOnce(
      new ApplyError("Please check the highlighted fields.", {
        phone: "Include the country code.",
      }),
    );
    render(<ApplyForm config={CONFIG} />);
    fillRequired();
    submit();

    await waitFor(() => {
      expect(screen.getByText(/include the country code/i)).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/full name/i)).toHaveValue("Chidinma Eze");
    expect(screen.getByLabelText(/course of study/i)).toHaveValue("Biochemistry");
  });

  it("confirms without promising a date, and repeats the no-fee warning", async () => {
    // No "within 5 days" — one person reads these, and a deadline in an automated
    // message is a complaint waiting to arrive. The fee sentence is a fraud control:
    // "we give you goods, you pay us later" is the shape of every advance-fee scam a
    // student has been warned about.
    mockSubmit.mockResolvedValueOnce(undefined);
    render(<ApplyForm config={CONFIG} />);
    fillRequired();
    submit();

    await waitFor(() => {
      expect(screen.getByText(/application received/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/never ask you to pay/i)).toBeInTheDocument();
    expect(screen.queryByText(/\d+ (working )?days/i)).toBeNull();
  });
});
