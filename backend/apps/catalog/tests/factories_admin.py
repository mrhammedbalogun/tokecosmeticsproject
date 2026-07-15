from django.contrib.auth import get_user_model


def staff_user(email="admin@toke.test"):
    User = get_user_model()
    u = User.objects.create_user(email=email, password="Str0ng!pass9")
    u.is_staff = True
    u.save(update_fields=["is_staff"])
    return u
