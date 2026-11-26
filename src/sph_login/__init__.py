"""Schulportal authentication, independent of the tasks using the session."""
from .session import AuthenticationError, Credentials, InteractionRequired, SphSession

__all__ = ["AuthenticationError", "Credentials", "InteractionRequired", "SphSession"]
