"""Payment gateway contract. Plan-08 ships bank_transfer; Plan-09 adds the four
networked gateways behind this same ABC (interface proven before the hard ones)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class InitiateResult:
    # action tells the storefront what to do: "bank_details" | "redirect" | "client_secret"
    action: str
    reference: str = ""
    data: dict = field(default_factory=dict)  # redirect_url / client_secret / bank details


class PaymentGateway(ABC):
    code: str
    supported_currencies: set[str]

    @abstractmethod
    def initiate(self, payment, order, return_url: str = "") -> InitiateResult: ...

    def verify(self, payment):  # overridden in Plan-09 (networked gateways)
        raise NotImplementedError

    def refund(self, payment, amount, reason):  # Plan-09
        raise NotImplementedError

    def parse_webhook(self, request):  # Plan-09
        raise NotImplementedError
