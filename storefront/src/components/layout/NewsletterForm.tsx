"use client";
import { useState } from "react";

export function NewsletterForm() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setState("loading");
    const res = await fetch("/api/newsletter", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, source: "footer" }),
    });
    setState(res.ok ? "done" : "error");
  }

  if (state === "done") return <p className="text-sm text-leaf">Thanks — you are on the list.</p>;

  return (
    <form onSubmit={submit} className="flex gap-2">
      <label className="sr-only" htmlFor="nl-email">Email address</label>
      <input
        id="nl-email" type="email" required value={email}
        onChange={(e) => setEmail(e.target.value)} placeholder="Your email"
        className="min-w-0 flex-1 rounded-[var(--radius-card)] border border-line bg-surface px-3 py-2 text-sm"
      />
      <button
        type="submit" disabled={state === "loading"}
        className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface hover:bg-accent-strong transition-colors disabled:opacity-60"
      >
        {state === "loading" ? "…" : "Subscribe"}
      </button>
      {state === "error" && <span className="text-sm text-red-600">Try again.</span>}
    </form>
  );
}
