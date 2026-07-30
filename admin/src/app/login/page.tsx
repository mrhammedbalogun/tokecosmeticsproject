import type { Metadata } from "next";
import { LoginForm } from "@/components/LoginForm";
import { gatePage } from "@/lib/session";
import { DEFAULT_NEXT, first, safeNext } from "@/lib/next-param";
import { loginAction } from "./actions";
import { StagingBadge } from "@/components/StagingBadge";

export const metadata: Metadata = {
  title: "Sign in",
  robots: { index: false, follow: false },
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function LoginPage({ searchParams }: { searchParams: SearchParams }) {
  // `searchParams` is a Promise in Next 16. `first()` collapses a repeated param BEFORE
  // validation: `?next=/a&next=/b` arrives as a string[], which `safeNext` would treat as
  // truthy and then call charCodeAt on — a 500 reachable from a hand-crafted URL.
  const next = safeNext(first((await searchParams).next), DEFAULT_NEXT);

  // The gate, not the proxy: preauth here means the password step is already done, so the
  // staff member goes to the TOTP step rather than being asked for it again; a live
  // session goes to the dashboard; the anomaly purges.
  await gatePage("login", "/login");

  return (
    <main className="flex min-h-full items-center justify-center px-6 py-16">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight">Toke Admin</h1>
          <StagingBadge />
        </div>
        <p className="mt-1 text-sm text-muted">Staff sign-in. Step 1 of 2.</p>
        <div className="mt-6 rounded-[var(--radius-card)] border border-line bg-surface p-6 shadow-sm">
          <LoginForm next={next} action={loginAction} />
        </div>
      </div>
    </main>
  );
}
