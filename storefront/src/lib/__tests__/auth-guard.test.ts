import { describe, expect, it } from "vitest";
import { decideAuth, decideLoginEntry } from "@/lib/auth-guard";

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

/**
 * The login page asks a DIFFERENT question from decideAuth, which is why this is a
 * separate function rather than a reuse of it.
 *
 * `decideAuth` answers "may this request proceed?" for a gated page, where an access
 * token alone is enough to attempt the fetch. The login page answers "should I skip the
 * form?" — and there, an access cookie alone is NOT enough, because the proxy gate keys
 * on the REFRESH cookie (`src/proxy.ts:40`). Skipping the form for an access-only
 * visitor sends them to /account, which the proxy bounces straight back to /login,
 * which skips the form again: an infinite redirect that never touches the API.
 */
describe("decideLoginEntry", () => {
  it("skips the form only when BOTH cookies are present", () => {
    expect(decideLoginEntry("a-token", "r-token", "/account/orders")).toEqual({
      kind: "go",
      to: "/account/orders",
    });
  });

  it("shows the form for an access cookie with no refresh — the redirect-loop case", () => {
    // proxy.ts:40 redirects /account* to /login whenever the refresh cookie is absent.
    // Honouring the access cookie here would ping-pong the visitor forever, and no API
    // call is involved so nothing would ever break the cycle.
    expect(decideLoginEntry("a-token", undefined, "/account")).toEqual({ kind: "form" });
  });

  it("shows the form when there is no session at all", () => {
    expect(decideLoginEntry(undefined, undefined, "/account")).toEqual({ kind: "form" });
  });

  it("renews instead of asking for a password when only the refresh survives", () => {
    // The rotation-race heal: the loser of a concurrent refresh arrives with a live
    // refresh and no access. Prompting for a password there is the bug this fixes.
    expect(decideLoginEntry(undefined, "r-token", "/account/orders")).toEqual({
      kind: "renew",
      to: "/api/auth/refresh-redirect?next=%2Faccount%2Forders",
    });
  });

  it("never round-trips an off-site destination", () => {
    expect(decideLoginEntry("a", "r", "//evil.example")).toEqual({ kind: "go", to: "/account" });
    expect(decideLoginEntry(undefined, "r", "https://evil.example")).toEqual({
      kind: "renew",
      to: "/api/auth/refresh-redirect?next=%2Faccount",
    });
  });
});
