from celery import shared_task

from apps.catalog.csv_io import import_products_csv, parse_csv_bytes


@shared_task
def import_products_csv_task(raw_bytes: bytes) -> dict:
    return import_products_csv(parse_csv_bytes(raw_bytes))
