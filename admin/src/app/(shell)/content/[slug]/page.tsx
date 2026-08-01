import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { PageEditor } from "@/components/content/PageEditor";
import { ApiError } from "@/lib/api";
import type { PageRow } from "@/lib/pages";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Edit page" };

export default async function EditContentPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const path = `/content/${slug}`;
  await requireAdmin(path);

  let page: PageRow;
  try {
    page = await fetchWithAuthOrBounce<PageRow>(
      `/admin/pages/${encodeURIComponent(slug)}/`,
      path,
    );
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 404) notFound();
    throw e;
  }

  return (
    <div>
      <div>
        <Link href="/content" className="text-sm text-muted hover:text-fg">
          ← Content
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">{page.title}</h1>
        <p className="mt-1 text-sm text-muted">
          <span className="font-mono">/page/{page.slug}</span> on the shop
        </p>
      </div>
      <div className="mt-6">
        <PageEditor page={page} />
      </div>
    </div>
  );
}
