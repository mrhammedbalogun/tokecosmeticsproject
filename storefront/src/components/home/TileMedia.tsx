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
  const mobileImg = mediaUrl(banner?.mobile_image ?? null);
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
  // Art direction, not responsive sizing: a phone image is a different CROP, so it is a
  // second <Image>, swapped by breakpoint. next/image cannot express this in one element.
  if (img && mobileImg) {
    return (
      <>
        <Image src={mobileImg} alt="" fill sizes="100vw" className="object-cover md:hidden" />
        <Image src={img} alt="" fill sizes={sizes} className="hidden object-cover md:block" />
      </>
    );
  }
  if (img || mobileImg) {
    return <Image src={(img ?? mobileImg)!} alt="" fill sizes={sizes} className="object-cover" />;
  }
  return <div aria-hidden className={`absolute inset-0 bg-gradient-to-br ${tone}`} />;
}

export function bannersFor(banners: CmsBanner[], placement: string): CmsBanner[] {
  return banners.filter((b) => b.placement === placement).sort((a, b) => a.sort - b.sort);
}

export function bannerFor(banners: CmsBanner[], placement: string): CmsBanner | null {
  return bannersFor(banners, placement)[0] ?? null;
}
