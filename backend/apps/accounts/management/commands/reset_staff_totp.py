"""Lost-device TOTP recovery — an OPERATOR action, deliberately not an endpoint.

`docs/runbooks/admin-gate.md` §6 named this command before it existed, precisely so
that whoever built it would not solve the problem the cheap way. The cheap way is a
"reset my two-factor" link behind an email confirmation, and it would immediately
become the cheapest door into the admin: a way to turn "I control this inbox" back into
full administrator access, which is exactly the fence TOTP was added to build. The
catastrophic scenario TOTP exists for (Plan-16 Amendment 1) is admin compromise ->
attacker edits the payout bank account -> every bank-transfer order pays them.

So recovery requires root SSH into the production host. The staff population is about
one and the store owner holds the key, so the operational cost is a few minutes and the
security saving is an entire attack surface.

The FIRST recourse is not this command: a staff member who still has their printed
recovery codes uses one at `/auth/admin-totp/recovery/`, which does the same voiding
without anybody being paged. This is for the case where the codes are gone too.
"""
import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.devices import revoke_all_devices
from apps.accounts.models import StaffEmailSecondFactor, StaffRecoveryCode, StaffTOTP
from apps.core.log_safety import scrub

security_logger = logging.getLogger("apps.security")


class Command(BaseCommand):
    help = (
        "Void a staff member's second factor (TOTP or email), recovery codes and "
        "trusted devices so they can set up again. Requires shell access on the "
        "server; there is no web equivalent."
    )

    def add_arguments(self, parser):
        parser.add_argument("email", help="the staff member's email address")

    def handle(self, *args, **options):
        User = get_user_model()
        email = options["email"].strip()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            # A CommandError rather than a silent no-op: a typo that quietly "succeeds"
            # sends the operator away believing they have fixed something.
            raise CommandError(f"No account with the address {email!r}.")

        totp_rows = StaffTOTP.objects.filter(user=user).delete()[0]
        email_rows = StaffEmailSecondFactor.objects.filter(user=user).delete()[0]
        code_rows = StaffRecoveryCode.objects.filter(user=user).delete()[0]
        # The same blast radius as the recovery endpoint, for the same reason: a
        # trusted browser is a pre-verified copy of the factor being voided.
        device_rows = revoke_all_devices(user)

        # ERROR -> a Sentry event. Somebody with shell access has just removed a staff
        # account's second factor; that is worth a permanent, alerting record whether it
        # was routine or not, and it is the only trace once the rows are gone.
        security_logger.error(
            "admin second factor reset from the command line for %s (%d TOTP "
            "enrolment(s), %d email factor(s), %d recovery code(s), %d trusted "
            "device(s) removed)",
            scrub(user.email),
            totp_rows,
            email_rows,
            code_rows,
            device_rows,
        )

        if not totp_rows and not email_rows:
            self.stdout.write(
                self.style.WARNING(
                    f"{user.email} had no confirmed second factor; nothing to void."
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"{user.email} can now set up again. They log in at /auth/admin-token/ "
                f"as usual; the next screen will be the method choice."
            )
        )
