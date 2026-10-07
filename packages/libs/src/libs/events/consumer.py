from abc import ABC, abstractmethod


class Consumer(ABC):
    """Abstract event consumer"""

    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass
