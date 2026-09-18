"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { MotionRoot } from "@/components/motion/Motion";

export function Providers({ children }: { children: React.ReactNode }) {
  // Defaults, not per-hook settings, because the two queries in this app —
  // ["cart"] and ["wishlist","skus"] — mount in the HEADER, so they run on every
  // page. TanStack v5 refetches on window focus by default, which meant every
  // tab-back and every mobile app-switch re-hit /api/cart and /api/wishlist.
  // Nothing here depends on that: every mutation already pushes the server's own
  // response into the cache (useCart's setQueryData, SignInStep's invalidate), so
  // focus refetching was re-fetching data we had just been handed.
  //
  // `retry` is the QUERY retry. Mutations keep their own default (0) — checkout's
  // idempotency-key contract lives there and is deliberately untouched. In practice
  // neither query retried anyway: both fetchers swallow a non-ok response and
  // return a default, so only a genuine network failure ever reached the retry path.
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <MotionRoot>{children}</MotionRoot>
    </QueryClientProvider>
  );
}
