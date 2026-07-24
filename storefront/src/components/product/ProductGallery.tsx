"use client";
import Image from "next/image";
import { useEffect, useState } from "react";
import type { ProductDetail } from "@/lib/catalog";
import { mediaUrl } from "@/lib/media";
import { usePdp } from "@/components/product/PdpContext";

/** Left column: main image + thumbnail strip with hover-zoom (mouse) and native
 * pinch-zoom (touch). Thumbnails are a keyboard-operable tablist. The zoom is a
 * progressive enhancement — keyboard users still see the full image and switch
 * via thumbnails — and its transition is neutralised under prefers-reduced-motion.
 * Picking a variant jumps to its linked image when one exists. */
export function ProductGallery({ product }: { product: ProductDetail }) {
  const { variant } = usePdp();
  const images = product.images;
  const [index, setIndex] = useState(0);
  const [zoom, setZoom] = useState<{ x: number; y: number } | null>(null);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    setReduced(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }, []);

  // Variant picked -> jump to its image if one is linked.
  useEffect(() => {
    if (!variant) return;
    const i = images.findIndex((img) => img.variant_id === variant.id);
    if (i >= 0) setIndex(i);
  }, [variant, images]);

  const current = images[index];
  if (!current) {
    return <div className="aspect-[3/4] rounded-[var(--radius-card)] bg-beige" aria-hidden />;
  }
  const zooming = zoom && !reduced;
  return (
    <div>
      <div
        className="relative aspect-[3/4] cursor-zoom-in overflow-hidden rounded-[var(--radius-card)] bg-beige"
        onMouseMove={(e) => {
          if (reduced) return;
          const r = e.currentTarget.getBoundingClientRect();
          setZoom({ x: ((e.clientX - r.left) / r.width) * 100, y: ((e.clientY - r.top) / r.height) * 100 });
        }}
        onMouseLeave={() => setZoom(null)}
      >
        <Image
          key={current.url}
          src={mediaUrl(current.url)!} alt={current.alt || product.name} fill priority
          sizes="(max-width: 1024px) 100vw, 50vw"
          className="object-cover transition-transform duration-200 motion-reduce:transition-none"
          style={zooming ? { transform: "scale(1.8)", transformOrigin: `${zoom!.x}% ${zoom!.y}%` } : undefined}
        />
      </div>
      {images.length > 1 && (
        <div className="mt-3 flex gap-2 overflow-x-auto" role="tablist" aria-label="Product images">
          {images.map((img, i) => (
            <button key={img.url} role="tab" aria-selected={i === index}
              aria-label={`Image ${i + 1}`}
              onClick={() => setIndex(i)}
              className={`relative h-20 w-16 shrink-0 overflow-hidden rounded-md border-2 ${i === index ? "border-accent" : "border-transparent"}`}>
              <Image src={mediaUrl(img.url)!} alt="" fill sizes="64px" className="object-cover" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
