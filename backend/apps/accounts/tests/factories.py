"""Staff-user helpers shared by the admin API tests across apps.

WHY THIS EXISTS. Before Plan-16 Task 2, `is_staff=True` was the whole of admin
authorisation, so a test that wanted "a staff member who can do this" wrote exactly
that. Now `is_staff` is only the gate: what a staff member may actually do comes from
their group. Every existing admin API test therefore needs a role, and the honest
translation of the old flag is the Owner role — Owner holds every scope by construction
(see the invariant at the bottom of `apps/accounts/rbac.py`), so those tests keep
testing what they were written to test rather than quietly becoming permission tests.

A test that wants to prove a NARROWER role is refused should not use `Owner`; see
`apps/accounts/tests/test_admin_role_matrix.py`, which is where role behaviour belongs.
"""
from django.contrib.auth.models import Group


def grant_role(user, role: str = "Owner"):
    """Put an existing staff user in a seeded role group. Returns the user."""
    user.groups.add(Group.objects.get(name=role))
    return user


def staff_user(django_user_model, email="staff@x.com", role="Owner", **kwargs):
    """A staff account in one role. `kwargs` pass through to `create_user`."""
    kwargs.setdefault("password", "pw12345!")
    user = django_user_model.objects.create_user(email=email, is_staff=True, **kwargs)
    return grant_role(user, role)
