/**
 * The SEO tab: title, description, and a preview of the search result they produce.
 *
 * THE PREVIEW MIRRORS THE STOREFRONT RATHER THAN APPROXIMATING IT — including the
 * `| Toke Cosmetics` suffix the root layout's title template appends, and the two
 * fallbacks the PDP applies when a field is blank. `lib/seo-preview.ts` cites the source
 * lines. A preview that showed a different string than what ships would be worse than
 * none: somebody would trim a title to fit a box measuring the wrong text.
 *
 * PRESENTATIONAL: no state of its own.
 */
import type { PanelProps } from "@/components/product/DetailsPanel";
import {
  buildSeoPreview,
  DESCRIPTION_LIMIT,
  TITLE_LIMIT,
  truncate,
} from "@/lib/seo-preview";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

function Counter({ length, limit }: { length: number; limit: number }) {
  const over = length > limit;
  return (
    <span className={`text-xs tabular-nums ${over ? "text-warn" : "text-muted"}`}>
      {length}/{limit}
      {over && " — will be cut short"}
    </span>
  );
}

export function SeoPanel({
  values,
  errors,
  onChange,
  siteUrl,
}: PanelProps & { siteUrl: string }) {
  const preview = buildSeoPreview({
    seoTitle: values.seo_title,
    seoDescription: values.seo_description,
    name: values.name,
    shortDescription: values.short_description,
    slug: values.slug,
    siteUrl,
  });

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-4">
        <label className="block text-xs text-muted">
          <span className="flex items-center justify-between">
            SEO title
            <Counter length={preview.title.length} limit={TITLE_LIMIT} />
          </span>
          <input
            type="text"
            value={values.seo_title}
            onChange={(e) => onChange("seo_title", e.target.value)}
            placeholder={values.name}
            className={`mt-1 ${FIELD}`}
          />
          {preview.titleIsFallback && (
            <p className="mt-1 text-xs text-muted">
              Empty, so the product name is used. That is often the right answer.
            </p>
          )}
          {errors.seo_title && <p className="mt-1 text-xs text-warn">{errors.seo_title}</p>}
        </label>

        <label className="block text-xs text-muted">
          <span className="flex items-center justify-between">
            SEO description
            <Counter length={preview.description.length} limit={DESCRIPTION_LIMIT} />
          </span>
          <textarea
            value={values.seo_description}
            onChange={(e) => onChange("seo_description", e.target.value)}
            rows={4}
            placeholder={values.short_description}
            className={`mt-1 ${FIELD}`}
          />
          {preview.descriptionIsFallback && !preview.descriptionIsEmpty && (
            <p className="mt-1 text-xs text-muted">
              Empty, so the short description is used.
            </p>
          )}
          {preview.descriptionIsEmpty && (
            // Not a validation error — the page still renders. But a result with no
            // description lets the search engine invent one from the page body, which is
            // how a product ends up described by its own cookie banner.
            <p className="mt-1 text-xs text-warn">
              Nothing here and no short description either, so search engines will write
              their own.
            </p>
          )}
          {errors.seo_description && (
            <p className="mt-1 text-xs text-warn">{errors.seo_description}</p>
          )}
        </label>
      </div>

      <div>
        <h2 className="text-xs text-muted">Search result preview</h2>
        <div className="mt-1 rounded-[var(--radius-card)] border border-line bg-surface p-4">
          <p className="truncate text-xs text-ok">{preview.url}</p>
          <p className="mt-1 text-base text-accent">{truncate(preview.title, TITLE_LIMIT)}</p>
          <p className="mt-1 text-sm text-muted">
            {preview.descriptionIsEmpty ? (
              <span className="italic">No description — one will be generated.</span>
            ) : (
              truncate(preview.description, DESCRIPTION_LIMIT)
            )}
          </p>
        </div>
        <p className="mt-2 text-xs text-muted">
          Includes the “{" | Toke Cosmetics"}” the site appends to every title, so the
          counter matches what actually ships.
        </p>
      </div>
    </div>
  );
}
