from apps.payments.gateways.base import (
    GatewayNotConfigured,
    InitiateResult,
    ManualVerificationOnly,
    PaymentGateway,
)


class BankTransferGateway(PaymentGateway):
    """Manual bank transfer — the ONLY live method at launch (see Plan-09b). No external
    HTTP: initiate() returns the merchant's bank details for the order's country and the
    order sits pending_payment until a staff member confirms receipt against the bank
    statement (payments.services.confirm_manual_receipt). Payment stays 'initiated'."""

    code = "bank_transfer"
    confirmation = "manual"
    reservation_ttl_minutes = 1440  # 24h — NG transfers are NIP-instant; the delay is staff hours

    def initiate(self, payment, order, return_url: str = "") -> InitiateResult:
        from apps.payments.models import BankAccount  # lazy: registry imports this module

        account = BankAccount.objects.filter(country=order.country, is_active=True).first()
        if account is None:
            # Fail loudly. The old SiteSetting lookup defaulted to "" and would render a
            # payment page with an empty account number — the customer wires into nowhere
            # and that money is genuinely unrecoverable. Checkout gates on this too, so
            # reaching here means the account was deactivated mid-checkout.
            raise GatewayNotConfigured(
                f"no active BankAccount for {order.country_id} — cannot show bank details"
            )
        return InitiateResult(
            action="bank_details",
            reference=order.number,
            data={
                "bank_name": account.bank_name,
                "account_name": account.account_name,
                "account_number": account.account_number,
                **account.extra,
                # Ordered, display-ready, per-market. The email iterates this rather than
                # naming fields, so a market that needs a sort code or SWIFT gets it
                # without a template change. Labels are what the customer reads.
                "bank_details": {
                    "Bank": account.bank_name,
                    "Account name": account.account_name,
                    "Account number": account.account_number,
                    **{k.replace("_", " ").capitalize(): v for k, v in account.extra.items()},
                },
                "amount": str(order.grand_total),
                "currency": order.currency_id,
                "reference": order.number,
                "instructions": account.instructions
                or "Use your order number as the transfer reference.",
            },
        )

    def verify(self, payment):
        """There is no machine to ask — the staff member reading the bank statement IS the
        verification (see confirm_manual_receipt). Declining in the gateway vocabulary
        rather than inheriting the base NotImplementedError is what keeps the customer's
        "check my payment" button returning their order status instead of a 500."""
        raise ManualVerificationOnly(
            "bank_transfer is confirmed by a human, not by the gateway"
        )
