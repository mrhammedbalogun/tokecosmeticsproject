import type { ProductDetail } from "@/lib/catalog";

/** Description / ingredients / directions / warnings / FAQs straight from product
 * fields (master spec). Native details/summary — keyboard + SR support for free.
 * `description` is backend-authored rich HTML (trusted admin content). */
export function PdpAccordions({ product }: { product: ProductDetail }) {
  const sections: { title: string; html?: string; text?: string }[] = [
    { title: "Description", html: product.description },
    { title: "Ingredients", text: product.ingredients },
    { title: "How to use", text: product.directions },
    { title: "Warnings", text: product.warnings },
  ];
  return (
    <div className="mt-10 divide-y divide-line border-y border-line">
      {sections.filter((s) => s.html || s.text).map((s, i) => (
        <details key={s.title} open={i === 0} className="group py-4">
          <summary className="flex cursor-pointer list-none items-center justify-between font-medium marker:hidden">
            {s.title}
            <span aria-hidden className="text-muted transition-transform group-open:rotate-45">+</span>
          </summary>
          {s.html
            ? <div className="prose-sm mt-3 max-w-none leading-relaxed text-muted"
                dangerouslySetInnerHTML={{ __html: s.html }} />
            : <p className="mt-3 leading-relaxed text-muted">{s.text}</p>}
        </details>
      ))}
      {product.faqs.length > 0 && (
        <details className="group py-4">
          <summary className="flex cursor-pointer list-none items-center justify-between font-medium">
            FAQs
            <span aria-hidden className="text-muted transition-transform group-open:rotate-45">+</span>
          </summary>
          <dl className="mt-3 space-y-4">
            {product.faqs.map((f) => (
              <div key={f.q}>
                <dt className="text-sm font-medium">{f.q}</dt>
                <dd className="mt-1 text-sm leading-relaxed text-muted">{f.a}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      {product.specs.length > 0 && (
        <details className="group py-4">
          <summary className="flex cursor-pointer list-none items-center justify-between font-medium">
            Details
            <span aria-hidden className="text-muted transition-transform group-open:rotate-45">+</span>
          </summary>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
            {product.specs.map((s) => (
              <div key={s.label} className="contents">
                <dt className="text-muted">{s.label}</dt><dd>{s.value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </div>
  );
}
