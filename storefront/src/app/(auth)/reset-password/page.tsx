import type { Metadata } from "next";
import Link from "next/link";
import { ResetPasswordForm } from "@/components/auth/ResetPasswordForm";
import { confirmResetAction } from "./actions";
import { first } from "@/lib/search-params";

export const metadata: Metadata = {
  title: "Set a new password",
  robots: { index: false, follow: true },
  // The reset token sits in this page's URL. Any outbound request could otherwise
  // carry it in a Referer header — same rule as /verify-email.
  referrer: "no-referrer",
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function ResetPasswordPage({ searchParams }: { searchParams: SearchParams }) {
  // `first()` collapses repeated params BEFORE use — `?uid=a&uid=b` arrives as an
  // array (see /login for the 500 this once caused).
  const params = await searchParams;
  const uid = first(params.uid) ?? "";
  const token = first(params.token) ?? "";

  return (
    <div className="w-full">
      <h1 className="font-display text-3xl">Set a new password</h1>
      {uid && token ? (
        <div className="mt-6">
          <ResetPasswordForm uid={uid} token={token} action={confirmResetAction} />
        </div>
      ) : (
        <div className="mt-6">
          <p role="alert" className="text-sm text-red-700">
            This reset link is incomplete. Please open the link from your email again —
            or request a fresh one.
          </p>
          <p className="mt-4 text-sm text-muted">
            <Link href="/forgot-password" className="underline hover:text-foreground">
              Request a new reset link
            </Link>
          </p>
        </div>
      )}
    </div>
  );
}
