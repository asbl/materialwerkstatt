from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar


ServiceType = TypeVar("ServiceType")


def application_service(factory: Callable[[Any], ServiceType]) -> Callable[[Any], ServiceType]:
    @wraps(factory)
    def service(application) -> ServiceType:
        with application._services_lock:
            if factory.__name__ not in application._services:
                application._services[factory.__name__] = factory(application)
            return application._services[factory.__name__]

    return service
