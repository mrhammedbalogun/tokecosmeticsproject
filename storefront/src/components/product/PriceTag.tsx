import { formatMoney, symbolFor } from "@/lib/country";

/** Money display. NEVER computes or rounds — formats the API strings only.
 * compare-at renders as a struck-through "was" price in the muted tone. */
export function PriceTag({
  amount,
  compareAt,
  currency,
  from = false,
  size = "md",
}: {
  amount: string;
  compareAt?: string | null;
  currency: string;
  from?: boolean;
  size?: "md" | "lg";
}) {
  const symbol = symbolFor(currency);
  return (
    <p className={size === "lg" ? "text-2xl font-medium" : "text-sm font-medium"}>
      {from && <span className="mr-1 text-muted font-normal">from</span>}
      <span>{formatMoney(amount, currency, symbol)}</span>
      {compareAt && (
        <>
          {" "}
          <span className="sr-only">was</span>
          <s className="ml-2 text-muted font-normal">
            {formatMoney(compareAt, currency, symbol)}
          </s>
        </>
      )}
    </p>
  );
}
