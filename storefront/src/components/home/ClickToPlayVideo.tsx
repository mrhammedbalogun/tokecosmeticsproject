"use client";

/** A poster with a play button; the <video> is only mounted once pressed.
 *
 * That is the entire point: a 3-minute film is tens of megabytes, and most visitors on
 * mobile data will never press play. Rendering the element up front — even paused —
 * invites the browser to start fetching.
 */
import Image from "next/image";
import { useState } from "react";

export function ClickToPlayVideo({ src, poster, label }: {
  src: string;
  poster: string | null;
  label: string;
}) {
  const [playing, setPlaying] = useState(false);

  if (playing) {
    return (
      <video
        className="absolute inset-0 h-full w-full object-cover"
        src={src}
        poster={poster ?? undefined}
        controls
        autoPlay
        playsInline
      />
    );
  }

  return (
    <>
      {poster ? (
        <Image src={poster} alt="" fill sizes="100vw" className="object-cover" />
      ) : (
        <div aria-hidden className="absolute inset-0 bg-black/40" />
      )}
      <button
        type="button"
        onClick={() => setPlaying(true)}
        aria-label={label}
        className="absolute inset-0 grid place-items-center"
      >
        <span
          aria-hidden
          className="grid h-16 w-16 place-items-center rounded-full bg-white/90 text-2xl text-black shadow-lg transition hover:scale-105"
        >
          ▶
        </span>
      </button>
    </>
  );
}
