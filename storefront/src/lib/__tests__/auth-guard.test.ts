import { describe, expect, it } from "vitest";
import { decideAuth } from "@/lib/auth-guard";

/**
 * The decision is kept pure and separate from the redirect that acts on it, because
 * `redirect()` throws NEXT_REDIRECT — testing the logic through it would mean asserting
 * on thrown control flow, and the interesting part (which of three routes we take) would
 * be the hardest thing to see.
 *
 * Why a "refresh" outcome exists at all: Server Components may READ cookies but never
 * WRITE them (Next 16 — cookies.md), so a rotated SimpleJWT token pair can only be
 * persisted by a Route Handler. An expired access token therefore cannot be renewed in
 * place; the user is bounced through a Route Handler that renews and sends them back.
 */
describe("decideAuth", () => {
  it("passes through when the access token is present", () => {
    expect(decideAuth("a-token", "r-token", "/account/orders")).toEqual({
      kind: "authenticated",
      token: "a-token",
    });
  });

  it("sends a wholly unauthenticated visitor to login, remembering the path", () => {
    expect(decideAuth(undefined, undefined, "/account/orders")).toEqual({
      kind: "login",
      to: "/login?next=%2Faccount%2Forders",
    });
  });

  it("renews via the route handler when only the refresh token survives", () => {
    // THE 30-MINUTE CASE: access expired, refresh valid. Sending this user to /login
    // would be a spurious logout — they have a perfectly good session.
    expect(decideAuth(undefined, "r-token", "/account/orders")).toEqual({
      kind: "refresh",
      to: "/api/auth/refresh-redirect?next=%2Faccount%2Forders",
    });
  });

  it("refuses to round-trip an off-site path into either redirect", () => {
    // currentPath is normally trusted (we build it), but it must never become an
    // open-redirect vector if a caller ever passes something attacker-influenced.
    expect(decideAuth(undefined, undefined, "//evil.example")).toEqual({
      kind: "login",
      to: "/login?next=%2Faccount",
    });
    expect(decideAuth(undefined, "r-token", "https://evil.example")).toEqual({
      kind: "refresh",
      to: "/api/auth/refresh-redirect?next=%2Faccount",
    });
  });

  it("encodes a query string in the remembered path", () => {
    expect(decideAuth(undefined, undefined, "/account/orders?page=2")).toEqual({
      kind: "login",
      to: "/login?next=%2Faccount%2Forders%3Fpage%3D2",
    });
  });
});
