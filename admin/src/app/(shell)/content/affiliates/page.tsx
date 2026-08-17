import type { Metadata } from "next";
import Link from "next/link";
import { HomePlacementEditor } from "@/components/content/HomePlacementEditor";
import { ApiError } from "@/lib/api";
import type { BannerRow, CountryOption } from "@/lib/banners";
import { storefrontUrl } from "@/lib/env";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Affiliates page" };

const PATH = "/content/affiliates";

/**
 * `/content/affiliates` — the artwork on the public referral page.
 *
 * ── WHY THIS EXISTS AS ITS OWN SCREEN ───────────────────────────────────────────────
 *
 * Banner artwork used to be homepage-only, so `/home-content` was the whole story and
 * `/content/banners` redirects there. /affiliates (2026-08-16) is the first page outside
 * the homepage to take banners, and there was NO WAY TO EDIT THEM — Hammed went looking
 * for "Content → Banners" on my instruction and correctly found nothing. Its two images
 * had to be attached from a Django shell, which is not a thing a marketer can do.
 *
 * They are NOT added to /home-content: that page's promise is "the landing page, top to
 * bottom, exactly as the customer scrolls it", and two tiles from a different page would
 * make it a lie.
 *
 * Everything else is the same machinery — `HomePlacementEditor` decides placement by
 * WHERE it sits, so there is no placement dropdown here either, and the writes go
 * through the same `content/banners/actions` (which revalidate this path too).
 */
export default async function AffiliatesContentPage() {
  await requireAdmin(PATH);

  let banners: BannerRow[] = [];
  let countryOptions: CountryOption[] = [];
  let error: string | null = null;
  try {
    const [bannerData, countryData] = await Promise.all([
      fetchWithAuthOrBounce<{ results: BannerRow[] } | BannerRow[]>("/admin/banners/", PATH),
      // Geo-targeting picker; the modal hides the control if this comes back empty.
      fetchWithAuthOrBounce<CountryOption[]>("/meta/countries/", PATH).catch(
        () => [] as CountryOption[],
      ),
    ]);
    banners = Array.isArray(bannerData) ? bannerData : (bannerData?.results ?? []);
    countryOptions = countryData.map((c) => ({ code: c.code, name: c.name }));
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include editing marketing artwork."
        : "The affiliates artwork could not be loaded.";
  }

  if (error) {
    return (
      <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
        {error}
      </p>
    );
  }

  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Affiliates page</h1>
        <p className="mt-1 text-sm text-muted">
          The two pictures on the referral programme page. Everything else on it — the
          commission rate, the tracking window, the payout minimums — comes from the
          programme settings, so it can never disagree with what actually gets paid.
          Both pictures are optional: leave one out and the page closes the gap rather
          than showing an empty box.{" "}
          <Link
            href={`${storefrontUrl()}/affiliates`}
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 hover:text-accent"
          >
            View the page
          </Link>
        </p>
      </div>

      <Section
        title="Hero image"
        blurb="The wide band across the very top, above “Already in.” Without it the page opens straight on the words."
      >
        <HomePlacementEditor
          placement="affiliate_hero"
          banners={banners}
          countryOptions={countryOptions}
          layout="grid"
          gridClass="grid-cols-1 lg:max-w-2xl"
        />
      </Section>

      <Section
        title="₦200k Club image"
        blurb="Sits beside the green panel further down the page. Without it the green panel runs the full width."
      >
        <HomePlacementEditor
          placement="affiliate_tier"
          banners={banners}
          countryOptions={countryOptions}
          layout="grid"
          gridClass="grid-cols-1 sm:max-w-xs"
        />
      </Section>
    </div>
  );
}

function Section({
  title,
  blurb,
  children,
}: {
  title: string;
  blurb: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
      <p className="mt-1 text-sm text-muted">{blurb}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}
