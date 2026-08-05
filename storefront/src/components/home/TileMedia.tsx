import Image from "next/image";
import type { CmsBanner } from "@/lib/cms";
import { mediaUrl } from "@/lib/media";

/** The one media layer every homepage tile shares: the banner's video (autoplay,
 * muted, looped, image as poster) beats its image beats the tile's built-in
 * brand-gradient tone. Absolutely positioned — the parent owns size and overlay. */
export function TileMedia({
  banner,
  tone,
  sizes = "100vw",
}: {
  banner?: CmsBanner | null;
  tone: string;
  sizes?: string;
}) {
  const img = mediaUrl(banner?.image ?? null);
  if (banner?.video_url) {
    return (
      <video
        className="absolute inset-0 h-full w-full object-cover"
        src={banner.video_url}
        poster={img ?? undefined}
        autoPlay
        muted
        loop
        playsInline
      />
    );
  }
  if (img) {
    return <Image src={img} alt="" fill sizes={sizes} className="object-cover" />;
  }
  return <div aria-hidden className={`absolute inset-0 bg-gradient-to-br ${tone}`} />;
}

export function bannersFor(banners: CmsBanner[], placement: string): CmsBanner[] {
  return banners.filter((b) => b.placement === placement).sort((a, b) => a.sort - b.sort);
}

export function bannerFor(banners: CmsBanner[], placement: string): CmsBanner | null {
  return bannersFor(banners, placement)[0] ?? null;
}
