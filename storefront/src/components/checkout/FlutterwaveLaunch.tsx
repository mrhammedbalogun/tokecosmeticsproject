"use client";
import { useEffect, useState } from "react";

/** Flutterwave uses a HOSTED page (not inline): redirect the browser to it. The customer
 * comes back to /checkout/return?ref=... which the server baked into the return URL. */
export function FlutterwaveLaunch({ data }: { data: Record<string, unknown> }) {
  const url = typeof data.redirect_url === "string" ? data.redirect_url : "";
  const [failed, setFailed] = useState(!url);

  useEffect(() => {
    if (url) window.location.assign(url);
    else setFailed(true);
  }, [url]);

  if (failed) {
    return (
      <p role="alert" className="text-sm text-red-700">
        We couldn&apos;t open the payment page. Please try again or choose another method.
      </p>
    );
  }
  return <p className="text-sm text-muted">Redirecting you to complete payment…</p>;
}
