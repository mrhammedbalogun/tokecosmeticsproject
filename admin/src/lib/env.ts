/**
 * Which API this build talks to, and whether that is production.
 *
 * The topbar shows a red STAGING badge whenever it is not, because the admin app is the
 * one surface where "which database am I looking at?" has consequences — refunding an
 * order, editing a payout account or revoking a staff member against the wrong
 * environment are all irreversible-ish and all look identical on screen.
 *
 * FAIL LOUD, NOT QUIET: an unset or unrecognised value reads as NOT production, so a
 * misconfigured deployment shows the badge rather than hiding it. The failure mode of
 * being told "staging" while on production is a moment's confusion; the reverse is a
 * production edit made in the belief it was a rehearsal.
 */
export const PROD_API_URL = "https://api.tokecosmetics.com";

export function apiUrlForDisplay(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "";
}

export function isProductionApi(url: string | undefined = apiUrlForDisplay()): boolean {
  if (!url) return false;
  return url.replace(/\/+$/, "").toLowerCase() === PROD_API_URL;
}

/** Short label for the badge: the API host, or "unset". */
export function apiLabel(url: string | undefined = apiUrlForDisplay()): string {
  if (!url) return "API unset";
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
