"use server";

/**
 * Store-directory writes (Plan-42). `products.manage` — the same scope the endpoints
 * check, re-read from the database on every request. Nothing here is authorization;
 * these actions are ergonomics around `apps/stores/admin_views.py`, which is the fence.
 *
 * ── THE 409 IS A FEATURE, NOT AN ERROR ──────────────────────────────────────────────
 *
 * `StoreLocationAdminSerializer` answers 409 with a list of rows that look like the one
 * being saved, and the operator decides. That is why the result type carries
 * `duplicates` separately from `fieldErrors`: a duplicate warning is not a validation
 * failure, the form must not paint it red beside a field, and the way past it is a
 * second submit carrying `confirm_duplicate` — never a client-side bypass.
 *
 * The same status code also comes back from the database's unique index (two operators
 * saving the same shop in the same second) with an empty `possible_duplicates`. The
 * form renders that as a plain message with no override, which is correct: there is
 * nothing to confirm, the row already exists.
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import type { DuplicateHint, StoreRow } from "@/lib/stores";

const PAGE = "/find-stores";

export interface StoreActionState {
  savedAt?: number;
  /** Keyed by serializer field name — rendered under the field it names. */
  fieldErrors?: Record<string, string>;
  /** A sentence for the top of the form: an unfielded 400, a 403, a dead API. */
  message?: string | null;
  /** 409 only. Empty array = the unique index refused it and there is nothing to confirm. */
  duplicates?: DuplicateHint[];
  duplicateMessage?: string;
}

export interface StoreInput {
  id: number | null;
  name: string;
  store_type: string;
  /** `core.Country`'s primary key IS its ISO code ("NG") — not an integer. */
  country: string | null;
  state_region: number | null;
  area_region: number | null;
  city_text: string;
  address: string;
  latitude: string;
  longitude: string;
  phone: string;
  phone_alt: string;
  whatsapp_phone: string;
  opening_hours: string;
  notes: string;
  is_active: boolean;
  /** Set by the "Save anyway" button after the operator has read the warning. */
  confirm_duplicate?: boolean;
}

/** DRF's error bodies come in two shapes — `{field: ["msg"]}` and `{detail: "msg"}` —
 *  and both reach here. Anything unrecognised becomes one honest sentence rather than
 *  a JSON blob rendered at an operator. */
function toState(e: unknown, fallback: string): StoreActionState {
  if (!(e instanceof ApiError)) return { message: "The API is not responding." };
  const data = (e.data ?? {}) as Record<string, unknown>;

  if (e.status === 409) {
    const hints = Array.isArray(data.possible_duplicates)
      ? (data.possible_duplicates as DuplicateHint[])
      : [];
    return {
      duplicates: hints,
      duplicateMessage:
        typeof data.detail === "string"
          ? data.detail
          : "This looks like a shop that is already on file.",
    };
  }
  if (e.status === 403) {
    return { message: "Your role does not include managing stores." };
  }

  const fieldErrors: Record<string, string> = {};
  for (const [key, value] of Object.entries(data)) {
    if (key === "detail") continue;
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[key] = first;
  }
  if (Object.keys(fieldErrors).length) return { fieldErrors };
  return { message: typeof data.detail === "string" ? data.detail : fallback };
}

/** Create and update share one action, the same shape as the pickup-location saves.
 *
 *  PATCH rather than PUT on update, so a field this form does not render can never be
 *  blanked by saving a form that never knew about it. */
export async function saveStoreAction(input: StoreInput): Promise<StoreActionState> {
  // Pre-checks ONLY for a friendlier inline message. Every one of them is re-proved by
  // the serializer, from ids the client sent and must not be trusted with.
  if (!input.name.trim()) {
    return { fieldErrors: { name: "A store needs a name customers will recognise." } };
  }
  if (!input.address.trim()) {
    return { fieldErrors: { address: "Customers need the street address to find the shop." } };
  }
  if (!input.country || input.state_region === null) {
    return { fieldErrors: { state_region: "Pick the country and state this shop is in." } };
  }
  const lat = input.latitude.trim();
  const lng = input.longitude.trim();
  if (Boolean(lat) !== Boolean(lng)) {
    // The serializer refuses a half-pin too; this only puts the message under the
    // empty field before the round trip.
    return {
      fieldErrors: {
        [lat ? "longitude" : "latitude"]:
          "A pin needs both coordinates — add this one or clear the other.",
      },
    };
  }

  const body: Record<string, unknown> = {
    name: input.name.trim(),
    store_type: input.store_type,
    country: input.country,
    state_region: input.state_region,
    area_region: input.area_region,
    city_text: input.city_text.trim(),
    address: input.address.trim(),
    // Blank coordinate fields must go as null, not "" — the model's DecimalField
    // rejects the empty string and the pin is genuinely optional.
    latitude: input.latitude.trim() || null,
    longitude: input.longitude.trim() || null,
    phone: input.phone.trim(),
    phone_alt: input.phone_alt.trim(),
    whatsapp_phone: input.whatsapp_phone.trim(),
    opening_hours: input.opening_hours.trim(),
    notes: input.notes.trim(),
    is_active: input.is_active,
  };
  if (input.confirm_duplicate) body.confirm_duplicate = true;

  try {
    if (input.id === null) {
      await fetchWithAuth("/admin/stores/", { method: "POST", body });
    } else {
      await fetchWithAuth(`/admin/stores/${input.id}/`, { method: "PATCH", body });
    }
  } catch (e) {
    return toState(e, "That store could not be saved.");
  }
  revalidatePath(PAGE);
  return { savedAt: Date.now() };
}

/**
 * Show or hide a store on the public locator.
 *
 * A bare `is_active` PATCH, deliberately carrying nothing else: the serializer skips the
 * duplicate check when no identifying field is touched, so flipping a row that has
 * always had a look-alike next door cannot pop a warning about a decision nobody is
 * making.
 */
export async function setStoreActiveAction(
  id: number,
  isActive: boolean,
): Promise<StoreActionState> {
  try {
    await fetchWithAuth(`/admin/stores/${id}/`, {
      method: "PATCH",
      body: { is_active: isActive },
    });
  } catch (e) {
    return toState(e, "That store could not be updated.");
  }
  revalidatePath(PAGE);
  return { savedAt: Date.now() };
}

/** DELETE archives — it does not remove the row. `restoreStoreAction` undoes it, and
 *  there is deliberately no purge. */
export async function archiveStoreAction(id: number): Promise<StoreActionState> {
  try {
    await fetchWithAuth(`/admin/stores/${id}/`, { method: "DELETE" });
  } catch (e) {
    return toState(e, "That store could not be archived.");
  }
  revalidatePath(PAGE);
  return { savedAt: Date.now() };
}

/** Brings an archived store back INACTIVE — never straight onto the website. The
 *  backend decides that; this action only reports what it said. */
export async function restoreStoreAction(id: number): Promise<StoreActionState> {
  try {
    await fetchWithAuth<StoreRow>(`/admin/stores/${id}/restore/`, { method: "POST" });
  } catch (e) {
    return toState(e, "That store could not be restored.");
  }
  revalidatePath(PAGE);
  return { savedAt: Date.now() };
}
