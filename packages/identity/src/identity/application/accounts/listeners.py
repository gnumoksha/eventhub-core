from libs.events import listener
from shared.infra.logger import logger

from identity.domain.models.account.events import AccountLoggedIn


@listener(AccountLoggedIn)
def log_account_login(event: AccountLoggedIn) -> None:
    logger.info("Account logged in", extra={"account_id": event.account_id})
