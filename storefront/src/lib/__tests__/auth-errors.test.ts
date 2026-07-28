import { describe, it, expect } from "vitest";
import {
  loginErrorMessage,
  registerErrorMessage,
  resetRequestErrorMessage,
  resetConfirmErrorMessage,
  accountErrorMessage,
} from "@/lib/auth-errors";

const TURNSTILE_BODY = { detail: "Human verification failed. Refresh the page and try again." };

describe("turnstile 403s are verification failures, not credential failures", () => {
  it("login surfaces the verification message instead of 'Email or password is incorrect'", () => {
    // Telling a real customer their password is wrong when the WIDGET failed
    // sends them to reset a password that was never the problem.
    const out = loginErrorMessage(403, TURNSTILE_BODY);
    expect(out).toMatch(/verification/i);
    expect(out).not.toMatch(/password is incorrect/i);
  });

  it("a bare 403 without the marker still reads as a credential rejection", () => {
    expect(loginErrorMessage(403, { detail: "Forbidden" })).toMatch(/password is incorrect/i);
  });

  it("register surfaces the verification message on a turnstile 403", () => {
    const out = registerErrorMessage(403, TURNSTILE_BODY);
    expect(out.message).toMatch(/verification/i);
    expect(out.emailTaken).toBe(false);
  });
});

describe("resetRequestErrorMessage", () => {
  it("maps a turnstile 403 to the verification message", () => {
    expect(resetRequestErrorMessage(403, TURNSTILE_BODY)).toMatch(/verification/i);
  });
  it("maps a 429 to wait-and-retry copy", () => {
    expect(resetRequestErrorMessage(429, {})).toMatch(/too many|wait/i);
  });
  it("falls back without echoing internals", () => {
    const out = resetRequestErrorMessage(500, { detail: "psycopg.OperationalError" });
    expect(out).not.toMatch(/psycopg/);
  });
});

describe("accountErrorMessage", () => {
  it("echoes DRF field messages verbatim — they are written for end users", () => {
    const out = accountErrorMessage(400, {
      old_password: ["Current password is incorrect."],
    }, "fallback");
    expect(out).toMatch(/current password is incorrect/i);
  });
  it("uses the caller's fallback for a 5xx without echoing internals", () => {
    const out = accountErrorMessage(500, { detail: "Traceback" }, "Could not save.");
    expect(out).toBe("Could not save.");
  });
  it("maps 429 to wait-and-retry copy", () => {
    expect(accountErrorMessage(429, {}, "x")).toMatch(/too many|wait/i);
  });
});

describe("resetConfirmErrorMessage", () => {
  it("echoes Django's password validators verbatim — they are the instruction", () => {
    const out = resetConfirmErrorMessage(400, {
      password: ["This password is too short.", "This password is too common."],
    });
    expect(out).toMatch(/too short/);
    expect(out).toMatch(/too common/);
  });
  it("surfaces the invalid-link detail", () => {
    expect(resetConfirmErrorMessage(400, { detail: "Invalid or expired reset link." }))
      .toMatch(/invalid or expired/i);
  });
  it("falls back without echoing internals on a 5xx", () => {
    expect(resetConfirmErrorMessage(500, { detail: "Traceback" })).not.toMatch(/Traceback/);
  });
});

describe("loginErrorMessage", () => {
  it("gives ONE message for a rejected credential, whatever the backend said", () => {
    // Anti-enumeration. TokenObtainPairView already returns the same detail for a wrong
    // password and a nonexistent email, and the UI must not undo that. Checkout's
    // SignInStep says "Incorrect password — please try again.", which ASSERTS the account
    // exists; that is safe there only because it reaches its login phase via a register
    // probe that already established existence. On a standalone /login it is an oracle.
    const wrongPassword = loginErrorMessage(401, {
      detail: "No active account found with the given credentials",
    });
    const noSuchAccount = loginErrorMessage(401, {
      detail: "No active account found with the given credentials",
    });

    expect(wrongPassword).toBe(noSuchAccount);
    expect(wrongPassword).toBe("Email or password is incorrect.");
    expect(wrongPassword).not.toMatch(/password is wrong|no account|not found|doesn't exist/i);
  });

  it("does not leak an inactive-account distinction either", () => {
    expect(loginErrorMessage(401, { detail: "User account is disabled." })).toBe(
      "Email or password is incorrect.",
    );
  });

  it("tells a throttled user to wait, rather than that their password is wrong", () => {
    const msg = loginErrorMessage(429, { detail: "Request was throttled. Expected available in 42 seconds." });
    expect(msg).toMatch(/too many/i);
    expect(msg).not.toMatch(/incorrect/i);
  });

  it("surfaces field validation messages when the backend sends them", () => {
    expect(loginErrorMessage(400, { email: ["Enter a valid email address."] })).toBe(
      "Enter a valid email address.",
    );
  });

  it("joins multiple field messages", () => {
    expect(loginErrorMessage(400, {
      email: ["Enter a valid email address."],
      password: ["This field may not be blank."],
    })).toBe("Enter a valid email address. This field may not be blank.");
  });

  it("falls back to something honest on an unexpected shape or status", () => {
    const msg = loginErrorMessage(500, null);
    expect(msg).toMatch(/went wrong/i);
    expect(msg).not.toMatch(/incorrect/i);
  });

  it("never echoes an arbitrary upstream string back to the browser", () => {
    // A 500 body is not a user-facing message and may carry internals.
    expect(loginErrorMessage(500, { detail: "psycopg.OperationalError at /auth/token/" }))
      .not.toMatch(/psycopg/);
  });
});

describe("registerErrorMessage", () => {
  it("flags a duplicate email as a distinct outcome the page can act on", () => {
    // Registration unavoidably reveals whether an address is taken — the backend says
    // "Account already exists" and no UI wording can hide that. So unlike login, the
    // honest thing is to detect it and offer to sign in instead of hiding it behind a
    // vague error the user cannot act on.
    const out = registerErrorMessage(400, { email: ["Account already exists"] });
    expect(out.emailTaken).toBe(true);
  });

  it("does not mistake an ordinary email validation error for a duplicate", () => {
    const out = registerErrorMessage(400, { email: ["Enter a valid email address."] });
    expect(out.emailTaken).toBe(false);
    expect(out.message).toBe("Enter a valid email address.");
  });

  it("surfaces Django's password rules verbatim — they tell the user what to fix", () => {
    const out = registerErrorMessage(400, {
      password: ["This password is too short. It must contain at least 8 characters.",
                 "This password is too common."],
    });
    expect(out.message).toContain("at least 8 characters");
    expect(out.message).toContain("too common");
  });

  it("reports a throttled attempt as such", () => {
    expect(registerErrorMessage(429, { detail: "Request was throttled." }).message)
      .toMatch(/too many/i);
  });

  it("falls back without echoing upstream internals on a 5xx", () => {
    const out = registerErrorMessage(500, { detail: "psycopg.OperationalError" });
    expect(out.message).toMatch(/went wrong/i);
    expect(out.message).not.toMatch(/psycopg/);
    expect(out.emailTaken).toBe(false);
  });
});
