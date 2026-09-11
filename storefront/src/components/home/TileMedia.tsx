import Image from "next/image";
import { ClickToPlayVideo } from "@/components/home/ClickToPlayVideo";
import type { CmsBanner } from "@/lib/cms";
import { mediaUrl } from "@/lib/media";

/** The one media layer every homepage tile shares: the banner's video beats its image
 * beats the tile's built-in brand-gradient tone. How a video plays is the banner's
 * `video_mode`: "loop" autoplays muted with the image as poster; "click" shows the
 * poster with a play button and downloads nothing until it is pressed. Absolutely
 * positioned — the parent owns size and overlay. */
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
    if (banner.video_mode === "click") {
      return (
        <ClickToPlayVideo
          src={banner.video_url}
          poster={img}
          label={`Play the video${banner.title ? `: ${banner.title}` : ""}`}
        />
      );
    }
    return (
      <video
        className="absolute inset-0 h-full w-full object-cover"
        src={banner.video_url}
        poster={img ?? undefined}
        autoPlay
        muted
        loop
        playsInline
        // Without this the browser eagerly downloads the whole file on every visit —
        // it was missing until 2026-08-09.
        preload="metadata"
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

/**
 * Is this tile a FINISHED PIECE — one that already carries its own words — so the shop
 * must write nothing over it? (`Banner.image_mode`, 2026-09-10.)
 *
 * On a tile this means exactly one thing: no scrim, no heading, no paragraph, no button
 * of ours, and the whole tile becomes the link. It does NOT mean `object-contain` the
 * way it does on the hero. The hero can pin its own box to `aspect-[16/9]` and so can
 * promise nothing is cropped; a grid tile's shape is fixed by the row it sits in, and
 * containing inside it would letterbox differently at every viewport — on a phone
 * `ShopByCategory` is two columns, about 170px wide, where painted text is unreadable
 * however it is fitted. So the picture still fills the tile, and the admin's upload
 * check keeps telling the marketer how much will be cropped.
 *
 * A banner with no artwork is never "artwork": suppressing our copy would leave a tile
 * with a brand gradient and nothing on it at all.
 */
export function isArtwork(banner?: CmsBanner | null): boolean {
  return (
    banner?.image_mode === "artwork" &&
    Boolean(banner.image || banner.mobile_image || banner.video_url)
  );
}

export function bannersFor(banners: CmsBanner[], placement: string): CmsBanner[] {
  return banners.filter((b) => b.placement === placement).sort((a, b) => a.sort - b.sort);
}

export function bannerFor(banners: CmsBanner[], placement: string): CmsBanner | null {
  return bannersFor(banners, placement)[0] ?? null;
}
