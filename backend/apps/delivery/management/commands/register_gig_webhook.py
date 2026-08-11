"""One-time GIG webhook registration (go-live runbook step).

POSTs our receiver URL to GIG's webhook API and prints the returned secret,
which then goes into the VPS `backend/.env` as `GIG_WEBHOOK_SECRET` (followed
by a restart). Their docs show no envelope for this API and do not document
whether the third-party JWT is required — we send it; an unauthenticated API
will simply ignore the header.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.delivery.gig import client


class Command(BaseCommand):
    help = "Register the tracking-webhook URL with GIG and print the secret."

    def add_arguments(self, parser):
        parser.add_argument(
            "url",
            help="Public receiver URL, e.g. https://api.tokecosmetics.com/api/v1/webhooks/gig/",
        )

    def handle(self, *args, **options):
        url = options["url"]
        if not url.startswith("https://"):
            raise CommandError("The receiver URL must be https:// — the payload carries order movements.")
        response = client._request(
            "POST",
            f"{settings.GIG_WEBHOOK_API_BASE}/api/webhook/add-webhook-user",
            timeout=client.DEFAULT_TIMEOUT,
            retries=0,  # registration is a mutation; never blind-retry it
            json={"url": url},
            headers={"User-Agent": client.USER_AGENT, "access-token": client._token()},
        )
        if response.status_code != 200:
            raise CommandError(f"GIG answered HTTP {response.status_code}: {response.text[:500]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise CommandError(f"GIG returned non-JSON: {response.text[:500]}") from exc

        # Their doc shows a bare object; tolerate an envelope just in case.
        record = data.get("data", data) if isinstance(data, dict) else {}
        secret = str(record.get("secret", ""))
        self.stdout.write(f"GIG response: {data}")
        if secret:
            self.stdout.write(self.style.SUCCESS(
                f"\nSet on the VPS backend/.env and restart:\n  GIG_WEBHOOK_SECRET={secret}"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "No `secret` field in the response — inspect the output above with GIG's docs."
            ))
