"use server";

/** Marketing settings writes (Plan-44). `settings.manage` — Owner-only, like the payout
 * account and the tax screens, and for the same kind of reason: the consent country list
 * is a legal position, and a pixel id decides which ad account receives the shop's
 * customer data. */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import type { ChannelCode, TestEventResult } from "@/lib/marketing-config";

export interface MarketingSaveState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
}

function fieldErrorsFrom(e: ApiError): MarketingSaveState {
  const data = e.data as Record<string, unknown> | undefined;
  const fieldErrors: Record<string, string> = {};
  for (const [key, value] of Object.entries(data ?? {})) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") fieldErrors[key] = first;
  }
  return Object.keys(fieldErrors).length ? { fieldErrors } : { message: "That could not be saved." };
}

export async function saveMarketingSettingsAction(input: {
  tracking_enabled?: boolean;
  purchase_value_basis?: "goods" | "grand_total";
  consent_required_countries?: string[];
}): Promise<MarketingSaveState> {
  try {
    await fetchWithAuth("/admin/marketing/settings/", { method: "PATCH", body: input });
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    return fieldErrorsFrom(e);
  }
  revalidatePath("/settings/marketing");
  return { savedAt: Date.now() };
}

export async function saveMarketingChannelAction(input: {
  code: ChannelCode;
  is_enabled: boolean;
  pixel_id: string;
  secondary_id: string;
  server_account_id: string;
  server_destination_id: string;
  browser_enabled: boolean;
  server_enabled: boolean;
  test_event_code: string;
}): Promise<MarketingSaveState> {
  // Friendlier inline messages only; the serializer is the real boundary.
  if (input.is_enabled && !input.pixel_id.trim()) {
    return {
      fieldErrors: {
        pixel_id: "A channel cannot be switched on without an ID — the tag would load and do nothing.",
      },
    };
  }
  if (input.code === "google_ads" && input.server_enabled
      && (!input.server_account_id.trim() || !input.server_destination_id.trim())) {
    return {
      fieldErrors: {
        server_account_id:
          "Server-side needs both the customer ID and the conversion action ID — the API is addressed separately from the tag.",
      },
    };
  }
  if (input.code === "google_ads" && input.pixel_id.trim() && !input.secondary_id.trim()) {
    // The single most common Google Ads misconfiguration: the conversion fires, GA4 sees
    // it, and the ad account's conversion column stays at zero.
    return {
      fieldErrors: {
        secondary_id: "Google Ads needs the conversion LABEL too, or the ad account counts nothing.",
      },
    };
  }
  try {
    await fetchWithAuth(`/admin/marketing/channels/${input.code}/`, {
      method: "PATCH",
      body: {
        is_enabled: input.is_enabled,
        pixel_id: input.pixel_id.trim(),
        secondary_id: input.secondary_id.trim(),
        server_account_id: input.server_account_id.trim(),
        server_destination_id: input.server_destination_id.trim(),
        browser_enabled: input.browser_enabled,
        server_enabled: input.server_enabled,
        test_event_code: input.test_event_code.trim(),
      },
    });
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    return fieldErrorsFrom(e);
  }
  revalidatePath("/settings/marketing");
  return { savedAt: Date.now() };
}

/**
 * Send a real event to the platform, with the credentials as configured RIGHT NOW.
 *
 * The only thing in the product that can tell Hammed a pasted token actually works.
 * Nothing in either test suite can: these four APIs cannot be exercised without a live
 * ad account, and every failure up to this point is silent — a wrong pixel id is
 * accepted, a revoked token is refused inside an HTTP 200, and a channel that has never
 * worked looks exactly like a channel with no sales yet.
 */
export async function sendTestEventAction(code: ChannelCode): Promise<TestEventResult> {
  try {
    return await fetchWithAuth<TestEventResult>(
      `/admin/marketing/channels/${code}/test-event/`, { method: "POST" },
    );
  } catch (e) {
    if (e instanceof ApiError) {
      const data = (e.data ?? {}) as TestEventResult;
      return { ok: false, error: data.error ?? "request_failed", missing_settings: data.missing_settings };
    }
    return { ok: false, error: "api_unreachable" };
  }
}
