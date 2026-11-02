from shared.domain.errors import EntityNotFound


class PayoutAccountNotFound(EntityNotFound):
    def __init__(self) -> None:
        super().__init__("Payout account not found")
