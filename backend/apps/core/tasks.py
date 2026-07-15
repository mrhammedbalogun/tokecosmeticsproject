from celery import shared_task


@shared_task
def ping():
    """Trivial demo task used to prove the Celery wiring works."""
    return "pong"
