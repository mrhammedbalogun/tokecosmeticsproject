import { describe, expect, it } from "vitest";
import { CSP_HEADER_NAME, REPORT_ONLY, buildCsp } from "@/lib/csp";

function directive(policy: string, name: string): string {
  const found = policy.split("; ").find((d) => d.startsWith(`${name} `));
  return found ?? "";
}

describe("the storefront CSP", () => {
  it("SHIPS REPORT-ONLY UNTIL SOMEBODY HAS READ REPORTS", () => {
    // A CSP written against Next's inline bootstrap, a CMS that emits arbitrary published
    // HTML, and three third-party payment SDKs WILL block something real on day one.
    // Enforcing it blind means finding that out from a customer who cannot pay.
    expect(REPORT_ONLY).toBe(true);
    expect(CSP_HEADER_NAME).toBe("Content-Security-Policy-Report-Only");
  });

  it("ALLOWS EVERY PAYMENT SDK THAT ACTUALLY INJECTS A SCRIPT", () => {
    // Found by reading the code, not by copying a starter policy: @paystack/inline-js and
    // @paypal/react-paypal-js both inject scripts and render iframes. Miss one and
    // checkout breaks for that gateway only — the worst kind of partial outage.
    const policy = buildCsp();
    for (const origin of ["https://js.paystack.co", "https://www.paypal.com"]) {
      expect(directive(policy, "script-src")).toContain(origin);
      expect(directive(policy, "frame-src")).toContain(origin);
    }
  });

  it("allows Turnstile, which login and registration depend on", () => {
    const policy = buildCsp();
    expect(directive(policy, "script-src")).toContain("https://challenges.cloudflare.com");
    expect(directive(policy, "frame-src")).toContain("https://challenges.cloudflare.com");
  });

  it("does NOT carry origins for gateways that hand off by redirect", () => {
    // Flutterwave uses window.location.assign to a hosted page — a top-level navigation
    // needs no CSP allowance, and listing it would widen the policy for nothing.
    const policy = buildCsp();
    expect(policy).not.toContain("flutterwave");
    expect(policy).not.toContain("stripe");
  });

  it("NEVER ALLOWS unsafe-eval IN PRODUCTION", () => {
    // Turbopack's HMR client needs it; the production bundle does not, and it is the
    // single directive that most weakens a policy.
    expect(directive(buildCsp({ dev: true }), "script-src")).toContain("'unsafe-eval'");
    expect(directive(buildCsp({ dev: false }), "script-src")).not.toContain("'unsafe-eval'");
    expect(directive(buildCsp(), "script-src")).not.toContain("'unsafe-eval'");
  });

  it("REFUSES TO BE FRAMED, because clickjacking a checkout is the attack", () => {
    expect(directive(buildCsp(), "frame-ancestors")).toBe("frame-ancestors 'none'");
  });

  it("pins form-action to self, which is the second layer under the CMS sanitiser", () => {
    // A <form> that survived sanitising could otherwise post a customer's input anywhere.
    expect(directive(buildCsp(), "form-action")).toBe("form-action 'self'");
  });

  it("blocks plugins and locks the base URI", () => {
    expect(directive(buildCsp(), "object-src")).toBe("object-src 'none'");
    expect(directive(buildCsp(), "base-uri")).toBe("base-uri 'self'");
  });

  it("allows the media CDN images actually come from", () => {
    expect(directive(buildCsp(), "img-src")).toContain("cloudfront.net");
  });

  it("has a default-src to fall back on", () => {
    // Without it, any directive nobody thought of is unrestricted.
    expect(directive(buildCsp(), "default-src")).toBe("default-src 'self'");
  });
});
