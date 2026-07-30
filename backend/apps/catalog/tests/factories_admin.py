from django.contrib.auth import get_user_model

from apps.accounts.tests.factories import grant_role


def staff_user(email="admin@toke.test", role="Owner"):
    """A staff account in a role. Owner by default — see apps/accounts/tests/factories.py
    for why the old bare `is_staff=True` translates to Owner rather than to no role."""
    User = get_user_model()
    u = User.objects.create_user(email=email, password="Str0ng!pass9")
    u.is_staff = True
    u.save(update_fields=["is_staff"])
    return grant_role(u, role)
