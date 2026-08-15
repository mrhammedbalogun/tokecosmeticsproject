/**
 * The ₦200k Club. Gold is the seasoning here and nowhere else on the page — the design
 * direction reserves it for "badges and small luxury details", and a tier card is
 * exactly that: the one thing on the screen allowed to feel like a reward.
 *
 * Rendered for every referrer, not only members. A locked tier with a real progress bar
 * is a reason to keep sharing; a tier that only appears once you have qualified is a
 * secret.
 */
import type { Tier } from "@/lib/referrals";

const PERKS = [
  "Monthly retainer opportunities",
  "Complimentary PR packages & products",
  "Early access to new launches",
];

export function EliteTierCard({ tier }: { tier: Tier }) {
  return (
    <section
      className={
        "rounded-[var(--radius-card)] border p-6 " +
        (tier.is_elite ? "border-gold/50 bg-gold/5" : "border-line bg-surface")
      }
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-gold">
            {tier.is_elite ? "Elite partner" : "Exclusive tier"}
          </p>
          <h3 className="mt-1 font-display text-2xl">{tier.club_name}</h3>
        </div>
        {tier.is_elite && (
          <span className="rounded-full bg-gold/15 px-3 py-1 text-xs font-medium text-gold">
            You&rsquo;re in ✦
          </span>
        )}
      </div>

      <p className="mt-3 text-sm text-muted">
        {tier.is_elite ? (
          <>
            You&rsquo;ve driven{" "}
            <strong className="font-medium text-foreground">{tier.qualifying_sales_display}</strong>{" "}
            in sales over the last {tier.window_days} days. Our team will be in touch about
            your partner benefits.
          </>
        ) : (
          <>
            Drive over {tier.threshold_display} in sales within any {tier.window_days}-day
            period to unlock elite status.
          </>
        )}
      </p>

      {!tier.is_elite && (
        <div className="mt-5">
          <div
            className="h-2 w-full overflow-hidden rounded-full bg-beige"
            role="progressbar"
            aria-valuenow={tier.progress_percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Progress towards ${tier.club_name}`}
          >
            <div
              className="h-full rounded-full bg-gold transition-[width] duration-500"
              style={{ width: `${tier.progress_percent}%` }}
            />
          </div>
          <p className="mt-2 text-sm text-muted">
            <strong className="font-medium text-foreground">{tier.qualifying_sales_display}</strong>{" "}
            of {tier.threshold_display} in the last {tier.window_days} days
          </p>
        </div>
      )}

      <ul className="mt-5 space-y-1.5 text-sm">
        {PERKS.map((perk) => (
          <li key={perk} className="flex gap-2">
            <span aria-hidden className={tier.is_elite ? "text-gold" : "text-muted"}>
              ✦
            </span>
            <span className={tier.is_elite ? "" : "text-muted"}>{perk}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
