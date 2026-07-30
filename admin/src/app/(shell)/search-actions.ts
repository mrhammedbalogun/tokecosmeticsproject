"use server";

/**
 * The topbar search, as a Server Function.
 *
 * WHY A SERVER FUNCTION AND NOT A BFF ROUTE + `fetch` FROM THE BROWSER. The admin access
 * token lives in an httpOnly cookie and must stay there; a browser fetch would need the
 * generic `/api/[...path]` proxy, which exists and would work — but a Server Function is
 * the shape this app already uses for every other authenticated call (login, the TOTP
 * ceremony, sign-out), it gets Next's Origin/Host check for free, and it keeps the API
 * path shape off the client bundle entirely. One mechanism, not two.
 *
 * IT RETURNS AN ERROR SHAPE, NEVER THROWS AND NEVER REDIRECTS. This runs on every
 * keystroke-after-debounce; a `redirect()` from here would yank a staff member off the
 * page they were working on because their access token happened to expire mid-word.
 * `fetchWithAuth` already renews silently and persists the rotated pair — that is exactly
 * what a Server Function may do and a Server Component may not — so the only 401 that
 * reaches here is one renewal could not fix, and the honest answer to that is a message in
 * the dropdown rather than a hijacked navigation. The next real page load hits
 * `requireAdmin` and bounces properly.
 */
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import {
  MIN_QUERY_LENGTH,
  type SearchResults,
  type SearchState,
} from "@/lib/search";

export async function searchAction(term: string): Promise<SearchState> {
  const query = term.trim();
  // Mirrors the backend's own minimum. NOT a duplicate control — Django enforces it and
  // this cannot be trusted — it just spares a guaranteed 400 on the way to the same
  // answer. See `lib/search.ts`.
  if (query.length < MIN_QUERY_LENGTH) return { query, results: null };

  try {
    const results = await fetchWithAuth<SearchResults>(
      `/admin/search/?q=${encodeURIComponent(query)}`,
    );
    return { query, results };
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 429) {
        return { query, results: null, error: "Too many searches. Try again in a minute." };
      }
      if (e.status === 401 || e.status === 403) {
        return { query, results: null, error: "Your session has expired. Reload the page." };
      }
      return { query, results: null, error: "Search is unavailable right now." };
    }
    throw e;
  }
}
