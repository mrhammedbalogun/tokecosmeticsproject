import { describe, it, expect } from "vitest";
import { loginErrorMessage, registerErrorMessage } from "@/lib/auth-errors";

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
