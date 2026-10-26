class DomainError(Exception):
    """A rule of the mail domain was broken."""


class ValidationError(DomainError):
    pass
