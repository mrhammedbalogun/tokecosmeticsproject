import { describe, expect, it } from "vitest";
import { CSP_HEADER_NAME, buildCsp } from "@/lib/csp";

function directive(policy: string, name: string): string {
  return policy.split("; ").find((d) => d.startsWith(`${name} `)) ?? "";
}

describe("the admin CSP", () => {
  it("IS ENFORCED, NOT REPORT-ONLY", () => {
    // The asymmetry with the storefront is deliberate. The admin has four dependencies,
    // no payment SDK and no third-party content — there is nothing here to discover by
    // watching reports — and it is the higher-value target: every customer's PII and the
    // order desk live behind it.
    expect(CSP_HEADER_NAME).toBe("Content-Security-Policy");
  });

  it("allows Turnstile, the ONLY external SCRIPT origin the admin has", () => {
    const policy = buildCsp();
    expect(directive(policy, "script-src")).toContain("https://challenges.cloudflare.com");
    expect(directive(policy, "frame-src")).toContain("https://challenges.cloudflare.com");
  });

  it("frames the storefront for the /home-content live preview, and only frames it", () => {
    // A frame is not a script: the zero-third-party-scripts rule is untouched.
    const policy = buildCsp();
    expect(directive(policy, "frame-src")).toContain("http://localhost:3000");
    expect(directive(policy, "script-src")).not.toContain("http://localhost:3000");
    expect(directive(policy, "connect-src")).not.toContain("http://localhost:3000");
  });

  it("CARRIES NO PAYMENT ORIGINS — the admin takes no money", () => {
    const policy = buildCsp();
    for (const vendor of ["paystack", "paypal", "stripe", "flutterwave"]) {
      expect(policy).not.toContain(vendor);
    }
  });

  it("allows data: images (TOTP QR) plus the media host the thumbnails need", () => {
    // The media host was lost once already, when a second headers() assignment in
    // next.config.ts silently overwrote the block that carried it (found 2026-08-06) —
    // broken thumbnails whose only evidence is a console CSP violation.
    const img = directive(buildCsp(), "img-src");
    expect(img).toContain("data:");
    expect(img).toContain("https://dk4ivng9pnc2t.cloudfront.net");
    // Images may come from the CDN and the API origin; scripts still may not.
    expect(directive(buildCsp(), "script-src")).not.toContain("cloudfront");
  });

  it("NEVER ALLOWS unsafe-eval IN PRODUCTION", () => {
    expect(directive(buildCsp({ dev: true }), "script-src")).toContain("'unsafe-eval'");
    expect(directive(buildCsp({ dev: false }), "script-src")).not.toContain("'unsafe-eval'");
    expect(directive(buildCsp(), "script-src")).not.toContain("'unsafe-eval'");
  });

  it("refuses to be framed", () => {
    expect(directive(buildCsp(), "frame-ancestors")).toBe("frame-ancestors 'none'");
  });

  it("locks form-action, base-uri and object-src", () => {
    const policy = buildCsp();
    expect(directive(policy, "form-action")).toBe("form-action 'self'");
    expect(directive(policy, "base-uri")).toBe("base-uri 'self'");
    expect(directive(policy, "object-src")).toBe("object-src 'none'");
  });

  it("has a default-src so an unlisted directive is not unrestricted", () => {
    expect(directive(buildCsp(), "default-src")).toBe("default-src 'self'");
  });
});
