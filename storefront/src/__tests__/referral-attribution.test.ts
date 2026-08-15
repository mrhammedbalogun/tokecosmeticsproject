/**
 * Attribution capture: the proxy end of the referral programme.
 *
 * This is the code path that decides who gets paid, driven entirely by a URL a stranger
 * controls, so the tests are mostly about what it REFUSES.
 */
import { describe, it, expect } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "@/proxy";
import { REFERRAL_COOKIE, normalizeReferralCode } from "@/lib/referral";

function runAt(path: string, headers: Record<string, string> = {}) {
  return proxy(new NextRequest(`http://localhost:3000${path}`, { headers }));
}

describe("referral code normalisation", () => {
  it("accepts a well-formed code in any case", () => {
    expect(normalizeReferralCode("amina7k3p")).toBe("AMINA7K3P");
    expect(normalizeReferralCode("  AMINA7K3P  ")).toBe("AMINA7K3P");
  });

  it("rejects anything that is not a code", () => {
    // The alphabet deliberately excludes I, O, 0 and 1 (they are misread off a phone
    // screen), so a code containing them was never minted by us.
    for (const bad of [
      "", "ABC", "amina 7k3p", "<script>", "AMINA-7K3P", "AMIN0", "AMINA1",
      "A".repeat(33), "../../etc/passwd", "AMINA7K3P; DROP TABLE",
    ]) {
      expect(normalizeReferralCode(bad), bad).toBe("");
    }
  });
});

describe("proxy referral capture", () => {
  it("stores a valid ?ref= in an httpOnly cookie for 30 days", () => {
    const cookie = runAt("/?ref=AMINA7K3P").cookies.get(REFERRAL_COOKIE);
    expect(cookie?.value).toBe("AMINA7K3P");
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie?.maxAge).toBe(60 * 60 * 24 * 30);
    // lax, not strict: the click almost always arrives from Instagram or WhatsApp, and
    // strict would drop the cookie on exactly that cross-site navigation.
    expect(cookie?.sameSite).toBe("lax");
  });

  it("captures the code on any route, not just the homepage", () => {
    const res = runAt("/product/vitamin-c-serum?ref=CHIDIQ7X2");
    expect(res.cookies.get(REFERRAL_COOKIE)?.value).toBe("CHIDIQ7X2");
  });

  it("uppercases a lowercase link", () => {
    expect(runAt("/?ref=amina7k3p").cookies.get(REFERRAL_COOKIE)?.value).toBe("AMINA7K3P");
  });

  it("sets nothing at all when there is no ?ref=", () => {
    expect(runAt("/").cookies.get(REFERRAL_COOKIE)).toBeUndefined();
  });

  it("ignores a malformed code rather than storing it", () => {
    // A visitor who mistyped a link should get the shop, not an error — and the cookie
    // jar should not become a place to park attacker-chosen strings.
    expect(runAt("/?ref=%3Cscript%3E").cookies.get(REFERRAL_COOKIE)).toBeUndefined();
    expect(runAt("/?ref=").cookies.get(REFERRAL_COOKIE)).toBeUndefined();
  });

  it("overwrites an existing attribution — last click wins", () => {
    // The rule is documented in lib/referral.ts. Pinned here because it is a money
    // decision that would otherwise be invisible in the diff that changed it.
    const res = runAt("/?ref=CHIDIQ7X2", { cookie: `${REFERRAL_COOKIE}=AMINA7K3P` });
    expect(res.cookies.get(REFERRAL_COOKIE)?.value).toBe("CHIDIQ7X2");
  });

  it("leaves an existing attribution alone on a visit with no ?ref=", () => {
    const res = runAt("/products", { cookie: `${REFERRAL_COOKIE}=AMINA7K3P` });
    expect(res.cookies.get(REFERRAL_COOKIE)).toBeUndefined(); // no Set-Cookie emitted
  });

  it("does not redirect to strip the parameter", () => {
    // A redirect would cost every referred landing a round-trip and would break UTM
    // parameters a referrer runs alongside it.
    const res = runAt("/?ref=AMINA7K3P");
    expect(res.headers.get("location")).toBeNull();
  });

  it("still captures the code on a login bounce from a gated account page", () => {
    // Someone who clicks a referral link that deep-links into /account is redirected to
    // login. The attribution must survive that hop, or their eventual order earns nobody
    // anything.
    const res = runAt("/account/orders?ref=AMINA7K3P");
    expect(res.headers.get("location")).toContain("/login");
    expect(res.cookies.get(REFERRAL_COOKIE)?.value).toBe("AMINA7K3P");
  });
});

describe("proxy /r/CODE short link", () => {
  it("sets the same cookie and sends the visitor to the homepage", () => {
    // The spoken/printed form of a referral link. Resolved in the proxy rather than as a
    // page so it costs no render and cannot 404.
    const res = runAt("/r/AMINA7K3P");
    expect(res.cookies.get(REFERRAL_COOKIE)?.value).toBe("AMINA7K3P");
    expect(res.cookies.get(REFERRAL_COOKIE)?.httpOnly).toBe(true);
    expect(res.headers.get("location")).toBe("http://localhost:3000/");
  });

  it("lowercases are accepted — people type codes as they hear them", () => {
    expect(runAt("/r/amina7k3p").cookies.get(REFERRAL_COOKIE)?.value).toBe("AMINA7K3P");
  });

  it("a malformed short code redirects without storing anything", () => {
    const res = runAt("/r/%3Cscript%3E");
    expect(res.cookies.get(REFERRAL_COOKIE)).toBeUndefined();
  });

  it("does not swallow deeper paths that merely start with /r/", () => {
    // `/r/CODE/anything` is not a referral link; sending it to the homepage would break
    // a real route added under /r/ later.
    const res = runAt("/r/AMINA7K3P/extra");
    expect(res.headers.get("location")).toBeNull();
    expect(res.cookies.get(REFERRAL_COOKIE)).toBeUndefined();
  });
});
