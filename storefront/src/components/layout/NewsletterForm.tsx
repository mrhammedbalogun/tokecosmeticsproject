"use client";
import { useState } from "react";

/** Newsletter capture. `variant="onAccent"` restyles it for the green NewsletterCta
 * band (a green-on-green button would be invisible) without duplicating the form
 * logic — the default variant is unchanged for the footer. */
export function NewsletterForm({ variant = "default" }: { variant?: "default" | "onAccent" }) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const onAccent = variant === "onAccent";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setState("loading");
    const res = await fetch("/api/newsletter", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, source: "footer" }),
    });
    setState(res.ok ? "done" : "error");
  }

  if (state === "done")
    return (
      <p className={`text-sm ${onAccent ? "text-surface" : "text-leaf"}`}>
        Thanks — you are on the list.
      </p>
    );

  return (
    <form onSubmit={submit} className="flex gap-2">
      <label className="sr-only" htmlFor="nl-email">Email address</label>
      <input
        id="nl-email" type="email" required value={email}
        onChange={(e) => setEmail(e.target.value)} placeholder="Your email"
        className={
          onAccent
            ? "min-w-0 flex-1 rounded-[var(--radius-card)] border border-surface/40 bg-surface px-3 py-2 text-sm text-foreground placeholder:text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
            : "min-w-0 flex-1 rounded-[var(--radius-card)] border border-line bg-surface px-3 py-2 text-sm"
        }
      />
      <button
        type="submit" disabled={state === "loading"}
        className={
          onAccent
            ? "rounded-[var(--radius-card)] bg-surface px-4 py-2 text-sm font-medium text-accent transition-colors hover:bg-beige disabled:opacity-60"
            : "rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface hover:bg-accent-strong transition-colors disabled:opacity-60"
        }
      >
        {state === "loading" ? "…" : "Subscribe"}
      </button>
      {state === "error" && (
        <span className={`text-sm ${onAccent ? "text-surface" : "text-red-600"}`}>Try again.</span>
      )}
    </form>
  );
}
