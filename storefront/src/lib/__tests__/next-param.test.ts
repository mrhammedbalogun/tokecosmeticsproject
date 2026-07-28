import { describe, expect, it } from "vitest";
import { safeNext } from "@/lib/next-param";

/**
 * `?next=` is attacker-controlled: it arrives in a URL a victim can be sent, and it is
 * obeyed AFTER a successful login. An unvalidated value is the classic login
 * open-redirect — the user really does authenticate, then lands on a lookalike site
 * with a fresh session and no reason to suspect anything.
 *
 * The rule is deliberately a strict allowlist (one leading slash, nothing that can be
 * read as a host) rather than a blocklist of bad prefixes.
 */
describe("safeNext", () => {
  it("keeps an ordinary in-app path", () => {
    expect(safeNext("/account/orders")).toBe("/account/orders");
  });

  it("keeps a path with a query string", () => {
    expect(safeNext("/account/orders?page=2")).toBe("/account/orders?page=2");
  });

  it("falls back when the parameter is missing", () => {
    expect(safeNext(null)).toBe("/account");
    expect(safeNext(undefined)).toBe("/account");
    expect(safeNext("")).toBe("/account");
  });

  it("rejects an absolute URL to another origin", () => {
    expect(safeNext("https://evil.example/login")).toBe("/account");
  });

  it("rejects a protocol-relative URL", () => {
    // "//evil.example" is a URL to another HOST, not a path — the single most
    // commonly missed case, because it does start with a slash.
    expect(safeNext("//evil.example")).toBe("/account");
  });

  it("rejects a backslash-disguised protocol-relative URL", () => {
    // Browsers normalise the backslash to a slash, so "/\evil.example" navigates
    // off-site while passing a naive "starts with / and not //" check.
    expect(safeNext("/\\evil.example")).toBe("/account");
    expect(safeNext("\\\\evil.example")).toBe("/account");
  });

  it("rejects a scheme-bearing value that does not start with a slash", () => {
    expect(safeNext("javascript:alert(1)")).toBe("/account");
    expect(safeNext("data:text/html,x")).toBe("/account");
  });

  it("rejects a bare path with no leading slash", () => {
    expect(safeNext("account/orders")).toBe("/account");
  });

  it("rejects a value whose leading whitespace or control chars hide the scheme", () => {
    // Browsers strip leading control characters and whitespace before parsing, so a
    // value that only LOOKS like a path after trimming must not be trusted.
    expect(safeNext(" \t/\\evil.example")).toBe("/account");
    expect(safeNext("\n//evil.example")).toBe("/account");
  });

  it("accepts a caller-supplied fallback", () => {
    expect(safeNext("//evil.example", "/login")).toBe("/login");
  });
});
