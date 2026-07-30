from django.contrib.auth.base_user import BaseUserManager
from django.db import IntegrityError, transaction


class UserManager(BaseUserManager):
    """Email-based user manager that assigns a unique Toke ID on create."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email).lower()

        # Retry on the rare toke_id collision.
        from .models import generate_toke_id

        for _ in range(5):
            user = self.model(email=email, toke_id=generate_toke_id(), **extra_fields)
            user.set_password(password)
            try:
                with transaction.atomic():
                    user.save(using=self._db)
                return user
            except IntegrityError as exc:
                if "toke_id" in str(exc).lower():
                    continue
                raise
        raise IntegrityError("Could not allocate a unique toke_id after several attempts")

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def admin_visible(self):
        """Every account an admin surface may show. THE base queryset for staff-facing
        customer reads — global search today, the Plan-18 customer list next.

        It exists as a manager method rather than as a line inside the search view so that
        there is one place to change when the definition moves. A staff-facing list and a
        staff-facing search that disagree about which customers exist is the same bug in
        two directions: whichever one shows more is a way around the other.

        WHAT IT EXCLUDES TODAY, and only this: accounts whose PII has already been
        anonymised. Deletion is a two-phase soft delete — `is_active` flips immediately,
        the data is overwritten 30 days later by `apps.accounts.tasks` — and an anonymised
        row is a `deleted-TK-XXXXXX@deleted.invalid` shell with nothing left to show. A
        deleted customer who is still findable by typing "deleted" would be a deletion
        promise that was not kept.

        It deliberately KEEPS inactive accounts inside the grace window: that customer can
        still ring up about an order they placed last week, and can still change their
        mind. `is_active` is on every row so the UI can say so.
        """
        from .models import ANONYMISED_EMAIL_DOMAIN

        return self.exclude(email__endswith=ANONYMISED_EMAIL_DOMAIN)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self._create_user(email, password, **extra_fields)
