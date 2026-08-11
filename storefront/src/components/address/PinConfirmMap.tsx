"use client";
import { useEffect, useRef, useState } from "react";
import { loadGoogleMaps } from "@/lib/googleMaps";

export interface LatLng {
  lat: number;
  lng: number;
}

interface Props {
  /** Where the map opens: the pin if set, else the Places pick / LGA centroid. */
  center: LatLng;
  /** True when the map opens on a real pick/pin rather than an LGA centroid. */
  precise: boolean;
  value: LatLng | null;
  onChange: (pin: LatLng) => void;
}

const round6 = (n: number) => Math.round(n * 1e6) / 1e6;

/**
 * The confirm-your-pin map (Plan-32b ruling 2): the pin — not the text — is
 * what a rider navigates by. The marker starts on the best guess we have and
 * the customer drags it (or taps the map) onto their gate. Coordinates are only
 * COMMITTED on interaction or a Places pick — an untouched LGA centroid must
 * never be saved as if it were a door (that would be a fake pin; null falls
 * back to the centroid server-side anyway, honestly).
 */
export function PinConfirmMap({ center, precise, value, onChange }: Props) {
  const holderRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const markerRef = useRef<google.maps.Marker | null>(null);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const g = await loadGoogleMaps();
      if (cancelled || !holderRef.current) return;
      if (!g) {
        setFailed(true);
        return;
      }
      if (!mapRef.current) {
        mapRef.current = new g.maps.Map(holderRef.current, {
          center,
          zoom: precise ? 17 : 13,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
          clickableIcons: false,
        });
        markerRef.current = new g.maps.Marker({
          map: mapRef.current,
          position: value ?? center,
          draggable: true,
        });
        const commit = (pos: google.maps.LatLng | null | undefined) => {
          if (pos) onChangeRef.current({ lat: round6(pos.lat()), lng: round6(pos.lng()) });
        };
        markerRef.current.addListener("dragend", () => commit(markerRef.current?.getPosition()));
        mapRef.current.addListener("click", (e: google.maps.MapMouseEvent) => {
          if (e.latLng) {
            markerRef.current?.setPosition(e.latLng);
            commit(e.latLng);
          }
        });
      }
    })();
    return () => {
      cancelled = true;
    };
    // The map is created once; recentering below handles later prop changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A new center (fresh Places pick, LGA change) moves an EXISTING map — the
  // customer's manually-placed pin is only repositioned when the caller also
  // cleared/replaced `value`, which the forms do on every new pick.
  useEffect(() => {
    if (!mapRef.current || !markerRef.current) return;
    const target = value ?? center;
    markerRef.current.setPosition(target);
    mapRef.current.panTo(target);
    if (precise) mapRef.current.setZoom(17);
  }, [center.lat, center.lng, value, precise]); // eslint-disable-line react-hooks/exhaustive-deps

  if (failed) {
    return (
      <p className="text-sm text-muted">
        The map could not load — no problem: we&rsquo;ll use your area&rsquo;s location for
        delivery planning.
      </p>
    );
  }

  return (
    <div>
      <div
        ref={holderRef}
        data-testid="pin-map"
        className="h-64 w-full rounded-[var(--radius-card)] border border-line"
      />
      <p className="mt-1 text-xs text-muted">
        {value
          ? "Pin saved — drag it or tap the map to adjust."
          : "Drag the pin (or tap the map) to your gate so the rider finds you first try."}
      </p>
    </div>
  );
}
