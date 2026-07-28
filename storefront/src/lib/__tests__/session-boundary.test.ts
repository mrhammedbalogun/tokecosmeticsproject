/**
 * A structural guard, not a behaviour test.
 *
 * `fetchWithAuth` and `fetchWithAuthRaw` write cookies, which is legal only in a Route
 * Handler or Server Function. Called from a Server Component they attempt a token
 * rotation they cannot persist, which blacklists the user's refresh token server-side and
 * silently ends a 14-day session — and a caller with a `catch` renders a normal-looking
 * page over the top of it. That is exactly how it shipped twice.
 *
 * `lib/session.ts` has a dev-time probe that catches this however deep the call chain is,
 * but only when the offending page is actually rendered. This test closes the gap at the
 * import boundary, cheaply and on every run: the writing fetchers belong to Route
 * Handlers. Server Components use `requireAuth` / `fetchWithAuthOrBounce`.
 *
 * Server Function modules (files opening with the `"use server"` directive) are
 * allowed too — the directive is exactly what makes cookie writes legal in a file,
 * so it is the honest marker, unlike a path list that drifts. Plan-15b's account
 * actions (profile, password change, deletion) are the first such users.
 */
import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

// vitest runs from the storefront root. The "scan is not vacuous" case below is what
// keeps a wrong path from turning this whole file into a silent pass.
const SRC = join(process.cwd(), "src");

/** Directories whose files may import the cookie-writing fetchers. */
const ALLOWED_PREFIXES = [join("app", "api")];

const WRITING_FETCHERS = /\bfetchWithAuth(Raw)?\b/;

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      return entry === "__tests__" || entry === "node_modules" ? [] : walk(full);
    }
    return /\.tsx?$/.test(entry) ? [full] : [];
  });
}

/** The import statement that pulls a writing fetcher out of lib/session. */
function importsAWritingFetcher(source: string): boolean {
  const importBlocks = source.matchAll(/import\s*\{([^}]*)\}\s*from\s*["']@\/lib\/session["']/g);
  for (const block of importBlocks) {
    if (WRITING_FETCHERS.test(block[1])) return true;
  }
  return false;
}

describe("cookie-writing fetchers stay out of Server Components", () => {
  it("is only imported from Route Handlers", () => {
    const offenders = walk(SRC)
      .filter((file) => file !== join(SRC, "lib", "session.ts"))
      .filter((file) => {
        const source = readFileSync(file, "utf8");
        if (!importsAWritingFetcher(source)) return false;
        // A Server Function module may write cookies, so the import is legal there.
        return !source.trimStart().startsWith('"use server"');
      })
      .map((file) => relative(SRC, file))
      .filter((rel) => !ALLOWED_PREFIXES.some((p) => rel.startsWith(p + sep)));

    expect(offenders).toEqual([]);
  });

  it("actually finds the Route Handlers that do use it (the scan is not vacuous)", () => {
    const users = walk(SRC)
      .filter((file) => file !== join(SRC, "lib", "session.ts"))
      .filter((file) => importsAWritingFetcher(readFileSync(file, "utf8")));

    expect(users.length).toBeGreaterThan(0);
  });
});
