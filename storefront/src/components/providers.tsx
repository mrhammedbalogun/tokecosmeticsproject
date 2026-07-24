"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { MotionRoot } from "@/components/motion/Motion";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={client}>
      <MotionRoot>{children}</MotionRoot>
    </QueryClientProvider>
  );
}
