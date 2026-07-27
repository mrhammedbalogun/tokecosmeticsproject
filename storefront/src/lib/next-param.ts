/**
 * Validation for the `?next=` redirect-back parameter.
 *
 * `next` is attacker-controlled: it arrives in a URL a victim can be sent, and it is
 * obeyed AFTER a successful login. Unvalidated, it is the classic login open-redirect —
 * the user genuinely authenticates, then lands on a lookalike site holding a fresh
 * session and with no reason to suspect anything.
 *
 * Deliberately an allowlist ("one leading slash, and nothing that can be read as a
 * host") rather than a blocklist of known-bad prefixes: blocklists lose to the next
 * encoding trick, and there have been many.
 *
 * Character codes rather than regex ranges here on purpose — the ranges that matter are
 * unprintable, and a source file containing literal control characters is a maintenance
 * trap of its own.
 *
 * Used by the login page, the register page, and the refresh-redirect Route Handler.
 * Anything that consumes `next` MUST pass it through here first.
 */
export const DEFAULT_NEXT = "/account";

const SPACE = 0x20;
const DEL = 0x7f;

/** Leading bytes a browser discards before parsing a URL: C0 controls and space. */
function leadingIgnoredLength(value: string): number {
  let i = 0;
  while (i < value.length && value.charCodeAt(i) <= SPACE) i++;
  return i;
}

/** Any control character left in the value. In a Location header, CR/LF splits the response. */
function hasControlChar(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code < SPACE || code === DEL) return true;
  }
  return false;
}

export function safeNext(
  value: string | null | undefined,
  fallback: string = DEFAULT_NEXT,
): string {
  if (!value) return fallback;

  // Validate what the BROWSER will act on, not the raw string: browsers strip leading
  // control characters and spaces first, so a newline-prefixed "//evil.example" would
  // otherwise pass a naive check and still navigate off-site.
  const trimmed = value.slice(leadingIgnoredLength(value));

  if (hasControlChar(trimmed)) return fallback;

  // Must be a path, not a URL bearing a scheme ("https:", "javascript:", "data:").
  if (!trimmed.startsWith("/")) return fallback;

  // "//host" and "/\host" address another ORIGIN despite starting with a slash — the
  // single most commonly missed case. Browsers normalise the backslash to a slash.
  if (trimmed.length > 1 && (trimmed[1] === "/" || trimmed[1] === "\\")) return fallback;

  return trimmed;
}
