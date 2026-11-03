import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from identity.infra.http.authentication import (
    CommonAuthenticatedSession,
    require_common_session,
    require_csrf,
)
from organizers.application.organization.service import OrganizationService, __get_service
from organizers.application.payout_account.service import (
    PayoutAccountService,
)
from organizers.application.payout_account.service import (
    __get_service as __get_payout_account_service,
)
from organizers.infra.http.routers.setup import setup_routers


@pytest.fixture
def client(service: OrganizationService, payout_account_service: PayoutAccountService):
    app = FastAPI()
    setup_routers(app)
    active_account = {"id": uuid.uuid4()}
    app.dependency_overrides[__get_service] = lambda: service
    app.dependency_overrides[__get_payout_account_service] = lambda: payout_account_service
    app.dependency_overrides[require_common_session] = lambda: CommonAuthenticatedSession(
        account_id=active_account["id"],
        organization_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
    )
    app.dependency_overrides[require_csrf] = lambda: None
    return TestClient(app), active_account


def test_create_organization_needs_only_public_name_and_can_add_legal_profile(client):
    test_client, active_account = client
    response = test_client.post(
        "/organizations",
        json={"public_name": "Event Crew"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["tax_id_type"] is None
    assert body["legal_name"] is None
    assert body["tax_id"] is None
    assert body["members"] == [{"account_id": str(active_account["id"]), "role": "OWNER"}]

    profile_response = test_client.patch(
        f"/organizations/{body['id']}",
        json={
            "legal_name": "Maria da Silva",
            "tax_id_type": "CPF",
            "tax_id": "529.982.247-25",
        },
    )

    assert profile_response.status_code == 200, profile_response.text
    assert profile_response.json()["tax_id_type"] == "CPF"
    assert profile_response.json()["tax_id"] == "*******4725"


def test_non_owner_cannot_manage_members(client):
    test_client, active_account = client
    created = test_client.post(
        "/organizations",
        json={"public_name": "Event Crew"},
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
    created = test_client.post(
        "/organizations",
        json={"public_name": "Event Crew"},
    ).json()
    response = test_client.patch(
        f"/organizations/{created['id']}",
        json={
            "legal_name": "Maria da Silva",
            "tax_id_type": "CPF",
            "tax_id": "11111111111",
        },
    )

    assert response.status_code == 422


def test_payout_account_response_masks_sensitive_values(client):
    test_client, _active_account = client
    created = test_client.post(
        "/organizations",
        json={"public_name": "Event Crew"},
    ).json()
    profile_response = test_client.patch(
        f"/organizations/{created['id']}",
        json={
            "legal_name": "Maria da Silva",
            "tax_id_type": "CPF",
            "tax_id": "52998224725",
        },
    )
    assert profile_response.status_code == 200, profile_response.text

    response = test_client.post(
        f"/organizations/{created['id']}/payout-account",
        json={
            "method": "PIX",
            "pix_key": "maria@example.com",
            "pix_key_type": "EMAIL",
            "holder_name": "Maria da Silva",
            "holder_tax_id": "52998224725",
        },
    )

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "PENDING"
    assert response.json()["pix_key"] == "*************.com"
    assert response.json()["holder_tax_id"] == "*******4725"
