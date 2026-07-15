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

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self._create_user(email, password, **extra_fields)
