"use client";
import Link from "next/link";

export function AccountMenu({ signedIn }: { signedIn: boolean }) {
  return signedIn ? (
    <Link href="/account" className="text-sm hover:text-accent">Account</Link>
  ) : (
    <Link href="/login" className="text-sm hover:text-accent">Sign in</Link>
  );
}
