from celery import shared_task

from .send import send_email


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_email_task(self, template_name: str, to, context: dict):
    try:
        send_email(template_name, to, context)
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc)
