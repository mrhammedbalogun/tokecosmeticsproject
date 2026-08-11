/**
 * Google Maps JS loader + the few Places calls we make (Plan-32b slice 3).
 *
 * This module is the ONLY file that talks to `window.google` — components go
 * through these functions so tests can mock one seam and so the "assist, never
 * a gate" ruling has a single enforcement point: every function here degrades
 * to null/[] when the key is absent or the script fails, and callers must treat
 * that as "the plain form still works".
 *
 * Places calls use the New Places JS classes (AutocompleteSuggestion / Place)
 * with a session token per lookup session — the token groups keystrokes and the
 * final details fetch into ONE billable session (design ruling 8: cost control
 * is structural). The token is renewed after every successful pick.
 */
"use client";

const CALLBACK = "__tokeMapsReady";

declare global {
  interface Window {
    google?: typeof google;
    [CALLBACK]?: () => void;
  }
}

export interface PlacePick {
  /** The street-level text for line1 (main text of the suggestion). */
  line1: string;
  lat: number;
  lng: number;
  /** administrative_area_level_2 — approximates the LGA in Nigeria. */
  lgaName: string | null;
  /** administrative_area_level_1 — the state. */
  stateName: string | null;
}

export interface Suggestion {
  id: string;
  mainText: string;
  secondaryText: string;
}

export function mapsConfigured(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY);
}

let loader: Promise<typeof google | null> | null = null;

/** Inject the Maps JS script once; resolve null (never reject) on any failure. */
export function loadGoogleMaps(): Promise<typeof google | null> {
  if (!mapsConfigured()) return Promise.resolve(null);
  if (typeof window === "undefined") return Promise.resolve(null);
  if (window.google?.maps) return Promise.resolve(window.google);
  if (loader) return loader;

  loader = new Promise((resolve) => {
    window[CALLBACK] = () => resolve(window.google ?? null);
    const script = document.createElement("script");
    const key = encodeURIComponent(process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? "");
    script.src =
      `https://maps.googleapis.com/maps/api/js?key=${key}` +
      `&v=weekly&libraries=places&loading=async&callback=${CALLBACK}`;
    script.async = true;
    script.onerror = () => {
      loader = null; // a later mount may retry (transient network, ad blocker off)
      resolve(null);
    };
    document.head.appendChild(script);
  });
  return loader;
}

let sessionToken: google.maps.places.AutocompleteSessionToken | null = null;

/** Street suggestions for the current keystrokes, NG-only. [] on any failure. */
export async function fetchStreetSuggestions(input: string): Promise<Suggestion[]> {
  const g = await loadGoogleMaps();
  if (!g || input.trim().length < 3) return [];
  try {
    sessionToken ??= new g.maps.places.AutocompleteSessionToken();
    const { suggestions } =
      await g.maps.places.AutocompleteSuggestion.fetchAutocompleteSuggestions({
        input,
        sessionToken,
        includedRegionCodes: ["ng"],
      });
    return suggestions
      .filter((s) => s.placePrediction)
      .map((s) => ({
        id: s.placePrediction!.placeId,
        mainText: s.placePrediction!.mainText?.text ?? s.placePrediction!.text.text,
        secondaryText: s.placePrediction!.secondaryText?.text ?? "",
      }));
  } catch {
    return []; // assist, never a gate
  }
}

/** Resolve a picked suggestion to coordinates + admin areas; null on any failure. */
export async function resolveSuggestion(id: string, mainText: string): Promise<PlacePick | null> {
  const g = await loadGoogleMaps();
  if (!g) return null;
  try {
    const place = new g.maps.places.Place({ id });
    await place.fetchFields({ fields: ["location", "addressComponents"] });
    sessionToken = null; // the details fetch closes the billing session
    const loc = place.location;
    if (!loc) return null;
    const component = (type: string) =>
      place.addressComponents?.find((c) => c.types.includes(type))?.longText ?? null;
    return {
      line1: mainText,
      lat: loc.lat(),
      lng: loc.lng(),
      lgaName: component("administrative_area_level_2"),
      stateName: component("administrative_area_level_1"),
    };
  } catch {
    return null;
  }
}
