import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { RegisterForm } from "@/components/auth/RegisterForm";
import { registerAction } from "./actions";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { decideLoginEntry } from "@/lib/auth-guard";
import { DEFAULT_NEXT, safeNext } from "@/lib/next-param";
import { first } from "@/lib/search-params";

export const metadata: Metadata = {
  title: "Create account",
  robots: { index: false, follow: true },
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function RegisterPage({ searchParams }: { searchParams: SearchParams }) {
  // `first()` before validating: `?next=/a&next=/b` arrives as an array, which safeNext
  // would treat as truthy and then call charCodeAt on.
  const next = safeNext(first((await searchParams).next), DEFAULT_NEXT);

  const jar = await cookies();
  // The same three-way entry decision as /login — someone already signed in has nothing to
  // register, and the access-only case must still render the form rather than bounce (see
  // decideLoginEntry for the redirect loop that would otherwise occur).
  const entry = decideLoginEntry(
    jar.get(ACCESS_COOKIE)?.value,
    jar.get(REFRESH_COOKIE)?.value,
    next,
  );
  if (entry.kind === "go") redirect(entry.to);
  if (entry.kind === "renew") redirect(entry.to);

  return (
    <div className="w-full">
      <h1 className="font-display text-3xl">Create your account</h1>
      <p className="mt-2 text-sm text-muted">
        Track orders, save addresses and check out faster.
      </p>
      <div className="mt-6">
        <RegisterForm next={next} action={registerAction} />
      </div>
    </div>
  );
}
