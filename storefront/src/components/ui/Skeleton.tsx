export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-line/70 ${className}`} aria-hidden />;
}
