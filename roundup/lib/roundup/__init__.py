"""roundup: session triage for agent sessions (corgi-roundup plugin)."""


class BackendError(Exception):
    """The backend (Corgi) is unreachable or reported an error. CLI exit code 3."""


class InputError(Exception):
    """A digest or judgments file is malformed or of an unknown version. CLI exit code 4."""
