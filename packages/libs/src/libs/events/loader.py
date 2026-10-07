import importlib
import pkgutil
import types


def _load_item(item: str | types.ModuleType, filename: str) -> None:
    """
    Loads a given package or module.
    """
    if isinstance(item, str):
        importlib.import_module(item)
        return

    for _, module_name, _ in pkgutil.walk_packages(
        item.__path__, item.__name__ + "."
    ):
        if module_name.rsplit(".", 1)[-1] == filename:
            importlib.import_module(module_name)


def load_listeners(item: str | types.ModuleType) -> None:
    """
    Loads all listeners from the given package or module.

    Args:
        item: The package or module to load listeners from. Can be a string
              representing the module name or a module object.

    Example:
        load_listeners("identity.domain.listeners") # Load listeners from a package

        import identity.domain
        load_listeners(identity.domain) # Load listeners from a module
    """
    _load_item(item, "listeners")


def load_events(item: str | types.ModuleType) -> None:
    """
    Loads all events from the given package or module.

    Args:
        item: The package or module to load events from. Can be a string
              representing the module name or a module object.

    Example:
        load_events("identity.domain.events") # Load events from a package

        import identity.domain
        load_events(identity.domain) # Load events from a module
    """
    _load_item(item, "events")
