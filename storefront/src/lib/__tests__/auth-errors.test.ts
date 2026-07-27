import { describe, it, expect } from "vitest";
import { loginErrorMessage } from "@/lib/auth-errors";

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
