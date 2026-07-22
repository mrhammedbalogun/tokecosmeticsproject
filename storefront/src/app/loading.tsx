import { Skeleton } from "@/components/ui/Skeleton";
export default function Loading() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-16">
      <Skeleton className="h-10 w-1/3" />
      <Skeleton className="mt-6 h-64 w-full" />
    </div>
  );
}
