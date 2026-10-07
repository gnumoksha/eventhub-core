from libs.events import listener
from shared.infra.logger import logger

from identity.domain.models.user.events import UserLoggedIn


@listener(UserLoggedIn)
def enrich_user(event: UserLoggedIn) -> None:
    logger.info("User logged in", extra={"user_id": event.user_id})
