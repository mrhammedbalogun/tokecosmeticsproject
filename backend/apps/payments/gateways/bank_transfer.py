from apps.core.models import SiteSetting
from apps.payments.gateways.base import (
    InitiateResult,
    ManualVerificationOnly,
    PaymentGateway,
)


class BankTransferGateway(PaymentGateway):
    """Manual bank transfer (large in NG). No external HTTP — initiate() returns the
    merchant's bank details from SiteSetting; the order sits pending_payment until an
    admin confirms receipt (Plan-18) or a Paystack dedicated account webhook lands
    (Plan-09). Payment stays 'initiated'."""

    code = "bank_transfer"
    supported_currencies = {"NGN"}
    confirmation = "manual"
    reservation_ttl_minutes = 1440  # 24h — NG transfers are NIP-instant; the delay is staff hours

    def initiate(self, payment, order, return_url: str = "") -> InitiateResult:
        return InitiateResult(
            action="bank_details",
            reference=order.number,
            data={
                "bank_name": SiteSetting.get_typed("bank_transfer.bank_name", ""),
                "account_name": SiteSetting.get_typed("bank_transfer.account_name", ""),
                "account_number": SiteSetting.get_typed("bank_transfer.account_number", ""),
                "amount": str(order.grand_total),
                "currency": order.currency_id,
                "reference": order.number,
                "instructions": "Use your order number as the transfer reference.",
            },
        )

    def verify(self, payment):
        """There is no machine to ask — the staff member reading the bank statement IS
        the verification. Declining in the gateway vocabulary (rather than inheriting the
        base NotImplementedError) is what keeps the customer's "check my payment" button
        returning their order status instead of a 500.
        """
        raise ManualVerificationOnly(
            "bank_transfer is confirmed by a human, not by the gateway"
        )
