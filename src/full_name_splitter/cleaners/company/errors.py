class CleanerError(Exception):
    pass


class FileReadError(CleanerError):
    pass


class EncodingError(CleanerError):
    pass


class ProviderError(CleanerError):
    pass


class ProviderAuthError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderTransientError(ProviderError):
    pass


class ProviderBadResponseError(ProviderError):
    pass
