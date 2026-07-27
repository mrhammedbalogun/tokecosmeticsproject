import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { LoginForm } from "@/components/auth/LoginForm";
import { loginAction } from "./actions";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { decideLoginEntry } from "@/lib/auth-guard";
import { DEFAULT_NEXT, safeNext } from "@/lib/next-param";
import { first } from "@/lib/search-params";

export const metadata: Metadata = {
  title: "Sign in",
  // A sign-in form has nothing worth indexing, and indexing it would publish `?next=` URLs.
  robots: { index: false, follow: true },
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function LoginPage({ searchParams }: { searchParams: SearchParams }) {
  // searchParams is a Promise in Next 16. `first()` collapses a repeated param BEFORE
  // validation: `?next=/a&next=/b` arrives as a string[], which safeNext treats as truthy
  // and then calls charCodeAt on — a 500 reachable from a hand-crafted URL.
  const raw = first((await searchParams).next);
  const next = safeNext(raw, DEFAULT_NEXT);

  const jar = await cookies();
  const entry = decideLoginEntry(
    jar.get(ACCESS_COOKIE)?.value,
    jar.get(REFRESH_COOKIE)?.value,
    next,
  );

  // Both cookies present — there is nothing to sign in to, so skip the form. Deliberately
  // NOT "access present": the proxy gates /account on the REFRESH cookie (proxy.ts:40), so
  // honouring an access-only cookie here would ping-pong the visitor between the two
  // forever. See decideLoginEntry.
  if (entry.kind === "go") redirect(entry.to);
  // Refresh only — the rotation-race loser: a live session whose access token is gone.
  // Renew instead of demanding a password. If the renewal itself fails, that handler
  // clears BOTH cookies before sending the user back here, so the next pass reaches the
  // form rather than bouncing again.
  if (entry.kind === "renew") redirect(entry.to);

  return (
    <div className="w-full">
      <h1 className="font-display text-3xl">Sign in</h1>
      <p className="mt-2 text-sm text-muted">
        Welcome back. Sign in to track your orders and check out faster.
      </p>
      <div className="mt-6">
        <LoginForm next={next} action={loginAction} />
      </div>
    </div>
  );
}
