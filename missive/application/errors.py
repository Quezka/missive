from ..domain import DomainError


class ApplicationError(Exception):
    """A use case could not be done; the message is for the user."""


class NotFound(ApplicationError):
    pass


class SourceError(ApplicationError):
    """The mail server could not be reached or refused us."""


__all__ = ["ApplicationError", "DomainError", "NotFound", "SourceError"]
