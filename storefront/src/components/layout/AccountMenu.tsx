"use client";
import Link from "next/link";

export function AccountMenu({ signedIn }: { signedIn: boolean }) {
  return signedIn ? (
    <Link href="/account" className="whitespace-nowrap text-sm hover:text-accent">Account</Link>
  ) : (
    <Link href="/login" className="whitespace-nowrap text-sm hover:text-accent">Sign in</Link>
  );
}
