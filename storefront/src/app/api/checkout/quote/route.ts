import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { REFERRAL_COOKIE, normalizeReferralCode } from "@/lib/referral";

/** Quote proxy (Plan-14 Task 3; guests since Plan-38). Proxies the read-only totals
 * endpoint so the cart/checkout UI can preview totals + validate a coupon before
 * placing the order. Never mutates anything server-side. A guest request (no session
 * cookies) is routed to the guest twin, which takes the inline address + guest_email
 * instead of a saved address id.
 *
 * THE REFERRAL CODE IS TAKEN FROM THE COOKIE AND ANY IN THE BODY IS DISCARDED, exactly
 * as `../route.ts` does at placement. Since 2026-08-27 an attributed order also discounts
 * the customer's own goods, so the quote has to know the code to show the row — and if
 * the preview and the placement could read different codes, they would compute different
 * totals and the `expected_total` guard would refuse the order at the last click. Same
 * source, same answer. It is not the security boundary (placement's cookie read is), but
 * there is no reason to let a browser preview a discount it will not get. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

export async function POST(req: Request) {
  const jar = await cookies();
  const isGuest = !jar.get(ACCESS_COOKIE)?.value && !jar.get(REFRESH_COOKIE)?.value;
  const { referral_code: _ignored, ...body } = await req.json().catch(() => ({}));
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const referral_code = normalizeReferralCode(jar.get(REFERRAL_COOKIE)?.value);
  const path = isGuest ? "/checkout/guest/quote/" : "/checkout/quote/";
  try {
    return json(
      await fetchWithAuth(path, { method: "POST", country, body: { ...body, referral_code } }),
    );
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
