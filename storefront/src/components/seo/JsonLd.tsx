/** Server component: emits one JSON-LD script tag. `<` is escaped so payload
 * content can never close the script tag (XSS hardening for API-sourced text). */
export function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\u003c") }}
    />
  );
}
