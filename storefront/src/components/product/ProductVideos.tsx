import { mediaUrl } from "@/lib/media";
import type { ProductDetail } from "@/lib/catalog";

/** The product's videos, as their own strip UNDER the gallery — deliberately not merged
 * into it. The gallery is index-keyed with variant→image sync, hover-zoom and a 3:4
 * `object-cover` crop, all of which are wrong for video (a 16:9 clip would be cropped;
 * zoom on a playing video is noise); folding them in waits for a poster field, which is
 * what makes gallery slides actually look like something before playback.
 *
 * `preload="metadata"` bounds the cost for visitors who never press play to one small
 * ranged request per video, and gives the player a first frame and a duration. No
 * autoplay, ever — these sit on mobile data. `object-contain` letterboxes whatever
 * aspect the clip really has instead of cropping it. */
export function ProductVideos({ product }: { product: ProductDetail }) {
  const videos = product.videos ?? [];
  if (videos.length === 0) return null;
  return (
    <section aria-label={`${product.name} videos`} className="mt-6 space-y-4">
      {videos.map((video, i) => (
        <video
          key={video.url}
          src={mediaUrl(video.url)!}
          controls
          playsInline
          preload="metadata"
          aria-label={`${product.name} video ${i + 1}`}
          className="w-full rounded-[var(--radius-card)] bg-beige object-contain"
        />
      ))}
    </section>
  );
}
