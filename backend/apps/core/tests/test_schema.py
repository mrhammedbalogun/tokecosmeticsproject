import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_openapi_schema_lists_register():
    c = APIClient()
    r = c.get("/api/schema/")
    assert r.status_code == 200
    body = r.content.decode()
    assert "/api/v1/auth/register/" in body
