/**
 * Minimal ambient types for `@paystack/inline-js` (v2.24), which ships no `.d.ts`.
 *
 * Deliberately narrow: it declares only `resumeTransaction`, the one method the
 * storefront uses (PaystackLaunch). The access code is minted server-side, so we never
 * touch the public-key/amount surface of `newTransaction()` — typing it here would
 * invite a client-priced transaction, which the checkout design forbids.
 *
 * Callback payload shapes follow the SDK README ("Callback Definitions").
 */
declare module "@paystack/inline-js" {
  export interface PaystackSuccessResponse {
    id: number;
    reference: string;
    message: string;
  }

  export interface PaystackErrorResponse {
    message: string;
  }

  export interface ResumeTransactionCallbacks {
    /** Customer completed payment. Confirm server-side before trusting it. */
    onSuccess?: (transaction: PaystackSuccessResponse) => void;
    /** Customer closed the checkout iframe. */
    onCancel?: () => void;
    /** The transaction could not be loaded. */
    onError?: (error: PaystackErrorResponse) => void;
    /** Checkout form loaded and is visible to the customer. */
    onLoad?: (transaction: { id: number; accessCode: string }) => void;
  }

  export default class PaystackPop {
    /** Resume a transaction created on our server via /transaction/initialize. */
    resumeTransaction(accessCode: string, callbacks?: ResumeTransactionCallbacks): unknown;
    isLoaded(): boolean;
  }
}
