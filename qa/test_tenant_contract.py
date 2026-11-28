"""HTTP isolation checks to run with the integrated tenancy fixture."""

import pytest


@pytest.fixture
def tenants(request):
    if not request.config.getoption("--tenant-fixture-plugin"):
        pytest.skip("Integrated tenancy fixture is pending")
    return request.getfixturevalue("tenant_world")


def headers(tenant):
    return {"Authorization": "Bearer " + tenant["token"]}


@pytest.mark.parametrize("resource", ["", "/config", "/usage", "/calls", "/messages", "/appointments", "/subscription"])
def test_tenant_session_only_reads_own_scope(tenants, resource):
    client, owner, other = (tenants[key] for key in ("client", "owner", "other"))
    url = f"/api/tenants/{owner['id']}{resource}"
    assert client.get(url, headers=headers(owner)).status_code == 200
    assert client.get(url).status_code == 401
    assert client.get(url, headers=headers(other)).status_code == 403


@pytest.mark.parametrize("resource", ["calls", "messages", "appointments"])
def test_tenant_objects_only_appear_in_own_scope(tenants, resource):
    client, owner, other = (tenants[key] for key in ("client", "owner", "other"))
    other_base = f"/api/tenants/{other['id']}/{resource}"
    owner_base = f"/api/tenants/{owner['id']}/{resource}"
    record = owner["records"][resource]
    assert client.get(f"{owner_base}/{record}", headers=headers(owner)).status_code == 200
    assert client.get(f"{other_base}/{other['records'][resource]}", headers=headers(other)).status_code == 200
    absent = client.get(f"{other_base}/{tenants['missing_record'][resource]}", headers=headers(other))
    foreign = client.get(f"{other_base}/{record}", headers=headers(other))
    assert absent.status_code == foreign.status_code == 404
    assert absent.json()["error"]["code"] == foreign.json()["error"]["code"]
    listing = client.get(other_base, headers=headers(other))
    assert listing.status_code == 200
    assert record not in listing.text


@pytest.mark.parametrize("resource", ["messages", "appointments"])
def test_tenant_writes_preserve_other_records(tenants, resource):
    client, owner, other = (tenants[key] for key in ("client", "owner", "other"))
    record = owner["records"][resource]
    own_url = f"/api/tenants/{owner['id']}/{resource}/{record}"
    other_url = f"/api/tenants/{other['id']}/{resource}/{record}"
    before = client.get(own_url, headers=headers(owner))
    assert before.status_code == 200
    payload = tenants["valid_updates"][resource]
    assert client.patch(own_url, headers=headers(other), json=payload).status_code == 403
    assert client.patch(other_url, headers=headers(other), json=payload).status_code == 404
    assert client.get(own_url, headers=headers(owner)).json() == before.json()
