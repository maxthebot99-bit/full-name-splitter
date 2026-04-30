class AddressCleanerError(Exception):
    pass


class FileReadError(AddressCleanerError):
    pass


class EncodingError(AddressCleanerError):
    pass


class ProviderError(AddressCleanerError):
    pass


class ProviderAuthError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderTransientError(ProviderError):
    pass


class ProviderBadResponseError(ProviderError):
    pass


class FetchError(AddressCleanerError):
    pass
