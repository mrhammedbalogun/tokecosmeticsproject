"""Order CSV export.

Mirrors `catalog/csv_io.py` and `inventory/csv_io.py` in shape. There is deliberately no
IMPORT counterpart: products and stock are catalogue data that can be re-stated, whereas an
order is a record of something that happened, and a CSV that could create or overwrite one
is a way to invent history. Orders arrive from checkout or from the Plan-23 importer, which
is a management command with a dry-run and a verification report — not a file upload.
"""
import csv
import io

from apps.orders.models import Order

COLUMNS = [
    "number", "status", "review_reason", "placed_at", "email", "country", "currency",
    "subtotal", "discount_total", "referral_discount_total", "shipping_total",
    "tax_total", "grand_total",
    "delivery_option_name", "tracking_carrier", "tracking_number", "source",
]


def export_orders_csv() -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS)
    writer.writeheader()
    # Newest first, matching the admin list. select_related because every row reads both.
    for order in Order.objects.select_related("country", "currency").order_by("-placed_at"):
        writer.writerow(
            {
                "number": order.number,
                "status": order.status,
                "review_reason": order.review_reason,
                "placed_at": order.placed_at.isoformat() if order.placed_at else "",
                "email": order.email,
                "country": order.country_id,
                "currency": order.currency_id,
                "subtotal": order.subtotal,
                "discount_total": order.discount_total,
                # Its own column, so the row still reconciles in a spreadsheet:
                # subtotal - discount - referral discount + delivery (+ tax) = grand total.
                "referral_discount_total": order.referral_discount_total,
                "shipping_total": order.shipping_total,
                "tax_total": order.tax_total,
                "grand_total": order.grand_total,
                "delivery_option_name": order.delivery_option_name,
                "tracking_carrier": order.tracking_carrier,
                "tracking_number": order.tracking_number,
                "source": order.source,
            }
        )
    return buf.getvalue()
