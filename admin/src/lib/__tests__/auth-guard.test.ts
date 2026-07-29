import { describe, it, expect } from "vitest";
import {
  DASHBOARD_PATH,
  LOGIN_PATH,
  PURGE_PATH,
  REFRESH_REDIRECT_PATH,
  TOTP_PATH,
  cookieState,
  decideAuth,
  routeClassFor,
} from "@/lib/auth-guard";

const NONE = {};
const PREAUTH = { preauth: "P" };
const PAIR = { access: "A", refresh: "R" };
const REFRESH_ONLY = { refresh: "R" };
const BOTH = { access: "A", refresh: "R", preauth: "P" };
const PREAUTH_PLUS_REFRESH = { refresh: "R", preauth: "P" };

describe("cookieState", () => {
  it("reads the four states off presence alone — never off token contents", () => {
    expect(cookieState(NONE)).toBe("none");
    expect(cookieState(PREAUTH)).toBe("preauth");
    expect(cookieState(PAIR)).toBe("session");
    expect(cookieState(REFRESH_ONLY)).toBe("session");
    expect(cookieState(BOTH)).toBe("anomaly");
    // Preauth alongside EITHER half of the pair is the anomaly — not just alongside both.
    expect(cookieState(PREAUTH_PLUS_REFRESH)).toBe("anomaly");
    expect(cookieState({ access: "A", preauth: "P" })).toBe("anomaly");
  });
});

describe("routeClassFor", () => {
  it("classifies the four route families, and does it by segment not by prefix", () => {
    expect(routeClassFor("/login")).toBe("login");
    expect(routeClassFor("/accept-invite")).toBe("public");
    expect(routeClassFor("/totp")).toBe("totp");
    expect(routeClassFor("/api/orders/")).toBe("bff");
    expect(routeClassFor("/")).toBe("app");
    expect(routeClassFor("/orders")).toBe("app");
    // Prefix collisions must NOT inherit a laxer class.
    expect(routeClassFor("/login-help")).toBe("app");
    expect(routeClassFor("/totp-reset")).toBe("app");
    expect(routeClassFor("/accept-invitations")).toBe("app");
    expect(routeClassFor("/api-docs")).toBe("app");
  });
});

// ── THE GATE MATRIX ────────────────────────────────────────────────────────────────
// Every row of the Plan-16 Task 5 ruling, asserted behaviourally rather than declared.

describe("gate matrix: no cookies", () => {
  it("lets /login render", () => {
    expect(decideAuth(NONE, "login", "/login")).toEqual({ kind: "allow" });
  });
  it("lets the public accept-invite page render", () => {
    expect(decideAuth(NONE, "public", "/accept-invite")).toEqual({ kind: "allow" });
  });
  it("sends every app route to /login with a next= to come back to", () => {
    expect(decideAuth(NONE, "app", "/orders/42")).toEqual({
      kind: "redirect",
      to: `${LOGIN_PATH}?next=${encodeURIComponent("/orders/42")}`,
    });
  });
  it("sends the TOTP step to /login — there is no step 1 to have completed", () => {
    expect(decideAuth(NONE, "totp", TOTP_PATH)).toEqual({ kind: "redirect", to: LOGIN_PATH });
  });
});

describe("gate matrix: preauth only", () => {
  it("lets the TOTP step render — that is the ONLY page it opens", () => {
    expect(decideAuth(PREAUTH, "totp", TOTP_PATH)).toEqual({ kind: "allow" });
  });
  it("sends app routes to the TOTP step, NOT to /login: step one is already done", () => {
    expect(decideAuth(PREAUTH, "app", "/orders")).toEqual({
      kind: "redirect",
      to: TOTP_PATH,
    });
  });
  it("sends /login to the TOTP step too — re-entering a password would be a step backwards", () => {
    expect(decideAuth(PREAUTH, "login", "/login")).toEqual({ kind: "redirect", to: TOTP_PATH });
  });
  it("still lets the public accept-invite page render", () => {
    expect(decideAuth(PREAUTH, "public", "/accept-invite")).toEqual({ kind: "allow" });
  });
  it("does NOT authenticate a BFF call: the generic proxy has no business with it", () => {
    expect(decideAuth(PREAUTH, "bff", "/api/orders/")).toEqual({ kind: "unauthenticated" });
  });
});

describe("gate matrix: full admin pair", () => {
  it("hands the access token to app routes", () => {
    expect(decideAuth(PAIR, "app", "/orders")).toEqual({ kind: "authenticated", token: "A" });
  });
  it("hands the access token to BFF calls", () => {
    expect(decideAuth(PAIR, "bff", "/api/orders/")).toEqual({
      kind: "authenticated",
      token: "A",
    });
  });
  it("bounces /login to the dashboard", () => {
    expect(decideAuth(PAIR, "login", "/login")).toEqual({
      kind: "redirect",
      to: DASHBOARD_PATH,
    });
  });
  it("bounces the TOTP step to the dashboard — the ceremony is over", () => {
    expect(decideAuth(PAIR, "totp", TOTP_PATH)).toEqual({
      kind: "redirect",
      to: DASHBOARD_PATH,
    });
  });
});

describe("gate matrix: refresh cookie alive, access cookie expired", () => {
  // The ordinary state every ten minutes: a 10-min access cookie under a 12-h refresh.
  it("bounces an app route through the renewal Route Handler, not to /login", () => {
    expect(decideAuth(REFRESH_ONLY, "app", "/orders")).toEqual({
      kind: "refresh",
      to: `${REFRESH_REDIRECT_PATH}?next=${encodeURIComponent("/orders")}`,
    });
  });
  it("tells a BFF call to renew rather than pretending it is unauthenticated", () => {
    expect(decideAuth(REFRESH_ONLY, "bff", "/api/orders/")).toEqual({ kind: "renew" });
  });
});

describe("gate matrix: preauth AND a session pair — the anomaly", () => {
  // Write-time mutual exclusion means no legitimate request can produce this. It must
  // NOT fall through to "the pair wins": that would make the anomaly indistinguishable
  // from a normal session and quietly reward whatever produced it.
  it("purges everything via the purge Route Handler, from an app route", () => {
    expect(decideAuth(BOTH, "app", "/orders")).toEqual({ kind: "purge", to: PURGE_PATH });
  });
  it("purges from /login itself", () => {
    expect(decideAuth(BOTH, "login", "/login")).toEqual({ kind: "purge", to: PURGE_PATH });
  });
  it("purges from the TOTP step", () => {
    expect(decideAuth(BOTH, "totp", TOTP_PATH)).toEqual({ kind: "purge", to: PURGE_PATH });
  });
  it("purges from the public accept-invite page", () => {
    expect(decideAuth(BOTH, "public", "/accept-invite")).toEqual({
      kind: "purge",
      to: PURGE_PATH,
    });
  });
  it("purges a BFF call rather than forwarding the access token it happens to hold", () => {
    expect(decideAuth(BOTH, "bff", "/api/orders/")).toEqual({ kind: "purge", to: PURGE_PATH });
  });
});

describe("the ?next= it builds is sanitised", () => {
  it("refuses a protocol-relative target that would leave the origin", () => {
    expect(decideAuth(NONE, "app", "//evil.example/x")).toEqual({
      kind: "redirect",
      to: `${LOGIN_PATH}?next=${encodeURIComponent(DASHBOARD_PATH)}`,
    });
  });
  it("refuses an absolute URL", () => {
    expect(decideAuth(NONE, "app", "https://evil.example/x")).toEqual({
      kind: "redirect",
      to: `${LOGIN_PATH}?next=${encodeURIComponent(DASHBOARD_PATH)}`,
    });
  });
});
