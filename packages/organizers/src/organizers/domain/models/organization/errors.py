from shared.domain.errors import AccessDenied, EntityNotFound


class OrganizationNotFound(EntityNotFound):
    def __init__(self) -> None:
        super().__init__("Organization not found")


class OrganizationAccessDenied(AccessDenied):
    def __init__(self) -> None:
        super().__init__("Only organization owners can manage it")


class PayoutAccountNotFound(EntityNotFound):
    def __init__(self) -> None:
        super().__init__("Payout account not found")
