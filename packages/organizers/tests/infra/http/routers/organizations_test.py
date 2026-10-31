import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from identity.infra.http.authentication import require_account_id, require_csrf
from organizers.application.organization.service import OrganizationService, __get_service
from organizers.infra.http.routers.setup import setup_routers


@pytest.fixture
def client(service: OrganizationService):
    app = FastAPI()
    setup_routers(app)
    active_account = {"id": uuid.uuid4()}
    app.dependency_overrides[__get_service] = lambda: service
    app.dependency_overrides[require_account_id] = lambda: active_account["id"]
    app.dependency_overrides[require_csrf] = lambda: None
    return TestClient(app), active_account


def test_create_organization_masks_tax_id(client):
    test_client, active_account = client
    response = test_client.post(
        "/organizations",
        json={
            "organization_type": "INDIVIDUAL",
            "public_name": "Event Crew",
            "legal_name": "Maria da Silva",
            "tax_id": "529.982.247-25",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["tax_id"] == "*******4725"
    assert body["members"] == [{"account_id": str(active_account["id"]), "role": "OWNER"}]


def test_non_owner_cannot_manage_members(client):
    test_client, active_account = client
    created = test_client.post(
        "/organizations",
        json={
            "organization_type": "INDIVIDUAL",
            "public_name": "Event Crew",
            "legal_name": "Maria da Silva",
            "tax_id": "52998224725",
        },
    ).json()
    organization_id = created["id"]
    owner = active_account["id"]
    staff = uuid.uuid4()
    test_client.post(
        f"/organizations/{organization_id}/members",
        json={"account_id": str(staff), "role": "STAFF"},
    )
    active_account["id"] = staff

    organization_response = test_client.get(f"/organizations/{organization_id}")
    payout_response = test_client.get(f"/organizations/{organization_id}/payout-account")

    response = test_client.post(
        f"/organizations/{organization_id}/members",
        json={"account_id": str(uuid.uuid4()), "role": "STAFF"},
    )

    assert owner != staff
    assert organization_response.json()["legal_name"] is None
    assert payout_response.status_code == 403
    assert response.status_code == 403


def test_invalid_cpf_is_rejected_by_api(client):
    test_client, _active_account = client
    response = test_client.post(
        "/organizations",
        json={
            "organization_type": "INDIVIDUAL",
            "public_name": "Event Crew",
            "legal_name": "Maria da Silva",
            "tax_id": "11111111111",
        },
    )

    assert response.status_code == 422


def test_payout_account_response_masks_sensitive_values(client):
    test_client, _active_account = client
    created = test_client.post(
        "/organizations",
        json={
            "organization_type": "INDIVIDUAL",
            "public_name": "Event Crew",
            "legal_name": "Maria da Silva",
            "tax_id": "52998224725",
        },
    ).json()

    response = test_client.post(
        f"/organizations/{created['id']}/payout-account",
        json={
            "method": "PIX",
            "pix_key": "maria@example.com",
            "holder_name": "Maria da Silva",
            "holder_tax_id": "52998224725",
        },
    )

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "PENDING"
    assert response.json()["pix_key"] == "*************.com"
    assert response.json()["holder_tax_id"] == "*******4725"
