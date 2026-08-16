/**
 * Attribution capture: the proxy end of the referral programme.
 *
 * This is the code path that decides who gets paid, driven entirely by a URL a stranger
 * controls, so the tests are mostly about what it REFUSES.
 */
import { afterEach, describe, it, expect, vi } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "@/proxy";
import { REFERRAL_COOKIE, normalizeReferralCode } from "@/lib/referral";

function runAt(path: string, headers: Record<string, string> = {}) {
  return proxy(new NextRequest(`http://localhost:3000${path}`, { headers }));
}

/** The proxy's one backend call: the code-exists lookup it makes before letting a NEW
 * code overwrite a STORED one. Tests that exercise that path stub the answer; every
 * other path must never fetch at all (the proxy runs on every navigation). */
function stubLookup(valid: boolean) {
  const mock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ valid }), { status: 200 }),
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => vi.unstubAllGlobals());

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
  it("stores a valid ?ref= in an httpOnly cookie for 30 days", async () => {
    const cookie = (await runAt("/?ref=AMINA7K3P")).cookies.get(REFERRAL_COOKIE);
    expect(cookie?.value).toBe("AMINA7K3P");
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie?.maxAge).toBe(60 * 60 * 24 * 30);
    // lax, not strict: the click almost always arrives from Instagram or WhatsApp, and
    // strict would drop the cookie on exactly that cross-site navigation.
    expect(cookie?.sameSite).toBe("lax");
  });

  it("captures the code on any route, not just the homepage", async () => {
    const res = await runAt("/product/vitamin-c-serum?ref=CHIDIQ7X2");
    expect(res.cookies.get(REFERRAL_COOKIE)?.value).toBe("CHIDIQ7X2");
  });

  it("uppercases a lowercase link", async () => {
    expect((await runAt("/?ref=amina7k3p")).cookies.get(REFERRAL_COOKIE)?.value).toBe("AMINA7K3P");
  });

  it("sets nothing at all when there is no ?ref=", async () => {
    expect((await runAt("/")).cookies.get(REFERRAL_COOKIE)).toBeUndefined();
  });

  it("ignores a malformed code rather than storing it", async () => {
    // A visitor who mistyped a link should get the shop, not an error — and the cookie
    // jar should not become a place to park attacker-chosen strings.
    expect((await runAt("/?ref=%3Cscript%3E")).cookies.get(REFERRAL_COOKIE)).toBeUndefined();
    expect((await runAt("/?ref=")).cookies.get(REFERRAL_COOKIE)).toBeUndefined();
  });

  it("overwrites an existing attribution with a REAL competing code — last click wins", async () => {
    // The rule is documented in lib/referral.ts. Pinned here because it is a money
    // decision that would otherwise be invisible in the diff that changed it.
    const lookup = stubLookup(true);
    const res = await runAt("/?ref=CHIDIQ7X2", { cookie: `${REFERRAL_COOKIE}=AMINA7K3P` });
    expect(res.cookies.get(REFERRAL_COOKIE)?.value).toBe("CHIDIQ7X2");
    expect(lookup).toHaveBeenCalledOnce();
  });

  it("a well-formed but NONEXISTENT code does not clobber a stored attribution", async () => {
    // Last-click covers a real competing code, not garbage: `?ref=BOGUS99X` is
    // trivially craftable by anyone (including a rival broadcasting a dead code), and
    // before this guard it silently destroyed a genuine referrer's pending commission.
    // The typed-code path (/api/referral) always had this protection; the link path
    // now matches it.
    stubLookup(false);
    const res = await runAt("/?ref=BOGUSQ9X2", { cookie: `${REFERRAL_COOKIE}=AMINA7K3P` });
    expect(res.cookies.get(REFERRAL_COOKIE)).toBeUndefined(); // no Set-Cookie emitted
  });

  it("keeps the stored attribution when the lookup cannot answer", async () => {
    // Conservative direction: an unverifiable new code must not destroy a verified old
    // one. The next click on the competing link gets another chance.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("backend down")));
    const res = await runAt("/?ref=CHIDIQ7X2", { cookie: `${REFERRAL_COOKIE}=AMINA7K3P` });
    expect(res.cookies.get(REFERRAL_COOKIE)).toBeUndefined();
  });

  it("sets a first attribution WITHOUT a lookup — the empty slot needs no referee", async () => {
    // No stored attribution means nothing can be clobbered, and checkout validates the
    // code anyway — so the common case (a fresh visitor clicking a link) costs zero
    // round-trips. The proxy runs on every navigation; it must not fetch on this path.
    const lookup = stubLookup(true);
    const res = await runAt("/?ref=AMINA7K3P");
    expect(res.cookies.get(REFERRAL_COOKIE)?.value).toBe("AMINA7K3P");
    expect(lookup).not.toHaveBeenCalled();
  });

  it("re-seeing the SAME code refreshes the 30 days without a lookup", async () => {
    const lookup = stubLookup(true);
    const res = await runAt("/?ref=AMINA7K3P", { cookie: `${REFERRAL_COOKIE}=AMINA7K3P` });
    expect(res.cookies.get(REFERRAL_COOKIE)?.value).toBe("AMINA7K3P");
    expect(lookup).not.toHaveBeenCalled();
  });

  it("leaves an existing attribution alone on a visit with no ?ref=", async () => {
    const res = await runAt("/products", { cookie: `${REFERRAL_COOKIE}=AMINA7K3P` });
    expect(res.cookies.get(REFERRAL_COOKIE)).toBeUndefined(); // no Set-Cookie emitted
  });

  it("does not redirect to strip the parameter", async () => {
    // A redirect would cost every referred landing a round-trip and would break UTM
    // parameters a referrer runs alongside it.
    const res = await runAt("/?ref=AMINA7K3P");
    expect(res.headers.get("location")).toBeNull();
  });

  it("still captures the code on a login bounce from a gated account page", async () => {
    // Someone who clicks a referral link that deep-links into /account is redirected to
    // login. The attribution must survive that hop, or their eventual order earns nobody
    // anything.
    const res = await runAt("/account/orders?ref=AMINA7K3P");
    expect(res.headers.get("location")).toContain("/login");
    expect(res.cookies.get(REFERRAL_COOKIE)?.value).toBe("AMINA7K3P");
  });
});

describe("proxy /r/CODE short link", () => {
  it("sets the same cookie and sends the visitor to the homepage", async () => {
    // The spoken/printed form of a referral link. Resolved in the proxy rather than as a
    // page so it costs no render and cannot 404.
    const res = await runAt("/r/AMINA7K3P");
    expect(res.cookies.get(REFERRAL_COOKIE)?.value).toBe("AMINA7K3P");
    expect(res.cookies.get(REFERRAL_COOKIE)?.httpOnly).toBe(true);
    expect(res.headers.get("location")).toBe("http://localhost:3000/");
  });

  it("lowercases are accepted — people type codes as they hear them", async () => {
    expect((await runAt("/r/amina7k3p")).cookies.get(REFERRAL_COOKIE)?.value).toBe("AMINA7K3P");
  });

  it("a malformed short code redirects without storing anything", async () => {
    // The original version of this test never asserted the redirect it is named for —
    // and the behaviour was in fact broken: a failed normalisation fell through to the
    // router, where no /r route exists, and 404'd. The excluded characters (0/1/I/O)
    // are exactly the ones people mistype from a printed card, so this is the SHAPE of
    // typo the "cannot 404" promise exists for.
    const res = await runAt("/r/%3Cscript%3E");
    expect(res.headers.get("location")).toBe("http://localhost:3000/");
    expect(res.cookies.get(REFERRAL_COOKIE)).toBeUndefined();
  });

  it("a too-short or lookalike-digit code still lands on the shop, not a 404", async () => {
    for (const path of ["/r/AB", "/r/AMIN0", "/r/AMINA1"]) {
      const res = await runAt(path);
      expect(res.headers.get("location"), path).toBe("http://localhost:3000/");
      expect(res.cookies.get(REFERRAL_COOKIE), path).toBeUndefined();
    }
  });

  it("does not swallow deeper paths that merely start with /r/", async () => {
    // `/r/CODE/anything` is not a referral link; sending it to the homepage would break
    // a real route added under /r/ later.
    const res = await runAt("/r/AMINA7K3P/extra");
    expect(res.headers.get("location")).toBeNull();
    expect(res.cookies.get(REFERRAL_COOKIE)).toBeUndefined();
  });
});
