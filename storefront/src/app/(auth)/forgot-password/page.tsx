import type { Metadata } from "next";
import { ForgotPasswordForm } from "@/components/auth/ForgotPasswordForm";
import { requestResetAction } from "./actions";

export const metadata: Metadata = {
  title: "Forgot password",
  robots: { index: false, follow: true },
};

// Deliberately NO signed-in redirect (unlike /login): a signed-in shopper who has
// forgotten their password is exactly who this page serves, and bouncing them to
// /account would strand them with a password they cannot type.
export default function ForgotPasswordPage() {
  return (
    <div className="w-full">
      <h1 className="font-display text-3xl">Forgot your password?</h1>
      <p className="mt-2 text-sm text-muted">
        Enter your email and we&apos;ll send you a link to set a new one.
      </p>
      <div className="mt-6">
        <ForgotPasswordForm action={requestResetAction} />
      </div>
    </div>
  );
}
