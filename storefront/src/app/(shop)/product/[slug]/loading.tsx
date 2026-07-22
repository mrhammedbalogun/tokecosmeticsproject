import { Skeleton } from "@/components/ui/Skeleton";
export default function Loading() {
  return (
    <div className="mx-auto grid max-w-7xl gap-10 px-4 py-16 md:grid-cols-2">
      <Skeleton className="aspect-square w-full" />
      <div>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="mt-4 h-6 w-1/3" />
        <Skeleton className="mt-8 h-12 w-full" />
      </div>
    </div>
  );
}
