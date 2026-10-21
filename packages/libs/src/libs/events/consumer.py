from abc import ABC, abstractmethod


class Consumer(ABC):
    """Abstract event consumer"""

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass
