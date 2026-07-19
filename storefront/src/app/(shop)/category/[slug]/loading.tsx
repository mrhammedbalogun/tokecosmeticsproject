import { Skeleton } from "@/components/ui/Skeleton";
export default function Loading() {
  return (
    <div className="mx-auto grid max-w-7xl grid-cols-2 gap-6 px-4 py-16 md:grid-cols-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i}>
          <Skeleton className="aspect-square w-full" />
          <Skeleton className="mt-3 h-4 w-3/4" />
          <Skeleton className="mt-2 h-4 w-1/2" />
        </div>
      ))}
    </div>
  );
}
