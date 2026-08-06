import type { Metadata } from "next";
import Link from "next/link";
import { HomePlacementEditor } from "@/components/content/HomePlacementEditor";
import {
  GoogleReviewsManager,
  type ReviewRow,
  type ReviewsMeta,
} from "@/components/content/GoogleReviewsManager";
import { ApiError } from "@/lib/api";
import type { BannerRow } from "@/lib/banners";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Home Content" };

const PATH = "/home-content";

/** `/home-content` — the landing page, edited in its own shape (rework 2026-08-06).
 * Sections appear here in the exact order the customer scrolls them, each showing its
 * CURRENT content: tiles with their artwork, built-ins badged where a slot is empty.
 * Clicking a tile opens the editor with the placement already decided — no placement
 * dropdown, no hunting a flat table for "the second category tile". The product rows
 * are collections, so those sections explain and link rather than duplicating the
 * product tooling. */

interface CollectionRow {
  id: number;
  name: string;
  slug: string;
  products: number[];
  is_active: boolean;
}

export default async function HomeContentPage() {
  await requireAdmin(PATH);

  let banners: BannerRow[] = [];
  let reviews: ReviewRow[] = [];
  let meta: ReviewsMeta = { rating: null, review_count_text: "", profile_url: "" };
  let collections: CollectionRow[] = [];
  let error: string | null = null;
  try {
    const [bannerData, reviewData, metaData, collectionData] = await Promise.all([
      fetchWithAuthOrBounce<{ results: BannerRow[] } | BannerRow[]>("/admin/banners/", PATH),
      fetchWithAuthOrBounce<{ results: ReviewRow[] } | ReviewRow[]>("/admin/google-reviews/", PATH),
      fetchWithAuthOrBounce<ReviewsMeta>("/admin/google-reviews-meta/", PATH),
      // Needs products.manage; a marketer without it still gets the rest of the page.
      fetchWithAuthOrBounce<{ results: CollectionRow[] } | CollectionRow[]>(
        "/admin/collections/",
        PATH,
      ).catch(() => [] as CollectionRow[]),
    ]);
    banners = Array.isArray(bannerData) ? bannerData : (bannerData?.results ?? []);
    reviews = Array.isArray(reviewData) ? reviewData : (reviewData?.results ?? []);
    meta = metaData ?? meta;
    collections = Array.isArray(collectionData) ? collectionData : (collectionData?.results ?? []);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include editing the homepage."
        : "The homepage content could not be loaded.";
  }

  if (error) {
    return (
      <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
        {error}
      </p>
    );
  }

  const bySlug = new Map(collections.map((c) => [c.slug, c]));
  const rowStatus = (slug: string) => {
    const collection = bySlug.get(slug);
    if (!collection) return "collection not created yet";
    const n = collection.products?.length ?? 0;
    return `${n} product${n === 1 ? "" : "s"}`;
  };

  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Home Content</h1>
        <p className="mt-1 text-sm text-muted">
          The landing page, top to bottom, exactly as the customer scrolls it. Every tile
          shows what is live right now — click it to change its text, link, artwork or
          schedule. Edits reach the shop within a minute. Tiles marked{" "}
          <span className="rounded-full border border-line px-1.5 py-0.5 text-[10px]">
            built-in
          </span>{" "}
          are showing the shop&apos;s built-in look; nothing ever goes blank.
        </p>
      </div>

      <Section n={1} title="News marquee" blurb="The scrolling bar at the very top.">
        <HomePlacementEditor placement="strip" banners={banners} layout="list" itemNoun="news item" />
      </Section>

      <Section
        n={2}
        title="Hero slider"
        blurb="The front door. Slides rotate every 6 seconds in the order below; one slide shows without slider chrome."
      >
        <HomePlacementEditor
          placement="hero"
          banners={banners}
          layout="slides"
          gridClass="sm:grid-cols-2 xl:grid-cols-3"
          itemNoun="slide"
        />
      </Section>

      <Section n={3} title="Shop by Category" blurb="Four portrait tiles.">
        <HomePlacementEditor
          placement="category"
          banners={banners}
          layout="grid"
          gridClass="grid-cols-2 lg:grid-cols-4"
        />
      </Section>

      <Section n={4} title="Shop by Concern" blurb="Three wide tiles.">
        <HomePlacementEditor
          placement="concern"
          banners={banners}
          layout="grid"
          gridClass="md:grid-cols-3"
        />
      </Section>

      <Section
        n={5}
        title="Feature tiles"
        blurb="The Glow Set feature beside the tokè × natural and Toke Naturals tiles."
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted">Glow Set feature</p>
            <HomePlacementEditor placement="feature" banners={banners} layout="grid" gridClass="grid-cols-1" />
          </div>
          <div className="space-y-4">
            <div>
              <p className="mb-1.5 text-xs font-medium text-muted">tokè × natural</p>
              <HomePlacementEditor placement="feature_nature" banners={banners} layout="grid" gridClass="grid-cols-1" />
            </div>
            <div>
              <p className="mb-1.5 text-xs font-medium text-muted">Toke Naturals</p>
              <HomePlacementEditor placement="feature_collection" banners={banners} layout="grid" gridClass="grid-cols-1" />
            </div>
          </div>
        </div>
      </Section>

      <RowSection
        n={6}
        title="“Loved by thousands” row"
        slug="best-sellers"
        status={rowStatus("best-sellers")}
      />

      <Section
        n={7}
        title="New for Men"
        blurb={`The tall banner beside the men's products. Products come from the ‘men’ collection — ${rowStatus("men")}.`}
      >
        <HomePlacementEditor placement="men" banners={banners} layout="grid" gridClass="sm:grid-cols-2 xl:grid-cols-3" />
      </Section>

      <Section
        n={8}
        title="For Women"
        blurb={`Products come from the ‘women’ collection — ${rowStatus("women")}.`}
      >
        <HomePlacementEditor placement="women" banners={banners} layout="grid" gridClass="sm:grid-cols-2 xl:grid-cols-3" />
      </Section>

      <Section
        n={9}
        title="For Babies"
        blurb={`Products come from the ‘babies’ collection — ${rowStatus("babies")}.`}
      >
        <HomePlacementEditor placement="babies" banners={banners} layout="grid" gridClass="sm:grid-cols-2 xl:grid-cols-3" />
      </Section>

      <RowSection
        n={10}
        title="“Natural Products” row"
        slug="new-arrivals"
        status={rowStatus("new-arrivals")}
      />

      <Section
        n={11}
        title="TikTok section"
        blurb="The promo tile beside four best sellers."
      >
        <HomePlacementEditor placement="tiktok" banners={banners} layout="grid" gridClass="sm:grid-cols-2 xl:grid-cols-3" />
      </Section>

      <Section n={12} title="Collections trio" blurb="Kids / Men's Essentials / Family.">
        <HomePlacementEditor
          placement="trio"
          banners={banners}
          layout="grid"
          gridClass="grid-cols-2 md:grid-cols-3"
        />
      </Section>

      <Section
        n={13}
        title="The Journal"
        blurb="The three journal teasers currently show built-in articles. They will bind to the blog automatically when the blog module ships — nothing to manage here yet."
      />

      <Section
        n={14}
        title="Google reviews"
        blurb="The closing “Loved on Google” section — header numbers plus the featured cards."
      >
        <GoogleReviewsManager reviews={reviews} meta={meta} />
      </Section>
    </div>
  );
}

function Section({
  n,
  title,
  blurb,
  children,
}: {
  n: number;
  title: string;
  blurb: string;
  children?: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="text-base font-semibold">
        {n} · {title}
      </h2>
      <p className="mb-4 mt-1 text-sm text-muted">{blurb}</p>
      {children}
    </section>
  );
}

/** A product row is a collection, not a banner — explain, count, and link. */
function RowSection({
  n,
  title,
  slug,
  status,
}: {
  n: number;
  title: string;
  slug: string;
  status: string;
}) {
  return (
    <Section
      n={n}
      title={title}
      blurb="This row shows a collection; it hides until the collection has products."
    >
      <p className="rounded-[var(--radius-card)] border border-line p-3 text-sm">
        <span className="font-mono text-xs text-muted">{slug}</span>
        <span className={`ml-2 ${status.startsWith("collection") ? "text-muted" : "text-ok"}`}>
          {status}
        </span>
        <Link
          href="/products"
          className="ml-3 underline underline-offset-2 hover:text-accent"
        >
          Manage under Products
        </Link>
      </p>
    </Section>
  );
}
