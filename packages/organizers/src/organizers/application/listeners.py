from identity.domain.models.account.events import AccountWasDeactivated
from libs.events import listener
from libs.time_utils import utc_now
from shared.infra.di import injectable
from shared.infra.logger import logger

from organizers.domain.models.organization.repository import OrganizationRepositoryDep
from organizers.domain.models.organization.values import MemberRole


@listener(AccountWasDeactivated)  # ty: ignore[invalid-argument-type]
@injectable(use_cache=False)  # always get a new database session for listeners. See var/docs/troubleshooting.md
async def remove_deactivated_account_memberships(
    event: AccountWasDeactivated, repository: OrganizationRepositoryDep
) -> None:
    """Remove operational memberships while preserving owner records."""
    account_id = event.account_id
    logger.info(f"Removing members for deactivated account {account_id}")

    organizations = await repository.list_for_account(account_id)
    for organization in organizations:
        member = next((member for member in organization.members if member.account_id == account_id), None)
        if member is not None and member.role != MemberRole.OWNER:
            organization.remove_member(account_id, now=utc_now())
            await repository.save(organization)

    logger.info(f"Removed members for deactivated account {account_id}")
