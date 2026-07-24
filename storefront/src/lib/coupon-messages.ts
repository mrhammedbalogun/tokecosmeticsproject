/** Specific, human coupon errors (backend error_code -> copy). Keep in sync with
 * validate_coupon's codes: not_found, inactive, not_started, expired, min_not_met,
 * wrong_currency, exhausted, user_exhausted, not_valid_for_items. */
const MESSAGES: Record<string, string> = {
  not_found: "That isn't a valid code.",
  inactive: "That code isn't active.",
  not_started: "That code isn't active yet.",
  expired: "That code has expired.",
  min_not_met: "Your bag doesn't meet this code's minimum spend.",
  wrong_currency: "That code isn't valid in your currency.",
  exhausted: "That code has been fully redeemed.",
  user_exhausted: "You've already used that code.",
  not_valid_for_items: "That code doesn't apply to the items in your bag.",
};

export function couponMessage(code: string): string {
  return MESSAGES[code] ?? "We couldn't apply that code — please try again.";
}
