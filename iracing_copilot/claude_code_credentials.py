r"""Reads Claude Code's own login so this project can call Claude without a
separate Anthropic API key - using whatever Pro/Max/Team (or Console)
account the user is already logged into Claude Code with.

This is different from (and simpler than) the `ant auth login` path
documented in README.md's "Authenticating Claude" section - that one reads
the separate ant-CLI profile format the plain `anthropic.Anthropic()`
client already resolves on its own; this module reads Claude Code's own
credentials file directly instead. Use whichever one you've actually got
logged in - diagnosis.py tries Claude Code's first, then falls back to the
SDK's normal resolution (env vars / ant-CLI profile).

File location: `~/.claude/.credentials.json`
(`%USERPROFILE%\.claude\.credentials.json` on Windows), confirmed against a
real file's structure:

    {"claudeAiOauth": {"accessToken": "...", "refreshToken": "...",
     "expiresAt": <ms epoch>, "refreshTokenExpiresAt": <ms epoch>,
     "scopes": [...], "subscriptionType": "team", ...}}

On macOS, Claude Code stores this in the OS Keychain instead of a plain
file, so this module won't find anything there - that's expected, not a
bug; use ANTHROPIC_API_KEY or `ant auth login` on macOS instead.

We deliberately don't implement our own OAuth refresh-token exchange here.
The installed SDK's own CredentialsFile class (anthropic.lib.credentials)
documents exactly this situation for a token it didn't mint itself:
"externally rotated ... re-read on every invocation ... the pattern for a
sidecar/daemon that mints the access token out-of-band." So instead, we
just re-read the file fresh on every API call - if Claude Code (or
anything else) refreshes the token in the background, we pick that up
automatically next call. If nothing refreshes it and it actually expires,
the API call fails with a clear error telling you to log in again.
"""

import json
import pathlib
import time

from anthropic.lib.credentials import AccessToken


class ClaudeCodeCredentialsError(RuntimeError):
    """Raised when Claude Code's credentials file can't be found, parsed, or
    looks expired."""


def default_credentials_path():
    return pathlib.Path.home() / ".claude" / ".credentials.json"


def is_available(path=None):
    """True if a Claude Code credentials file exists at the expected location."""
    return (pathlib.Path(path) if path else default_credentials_path()).exists()


class ClaudeCodeCredentials:
    """An AccessTokenProvider (anthropic.lib.credentials) that re-reads
    Claude Code's credentials file on every call. Pass to the SDK as
    `anthropic.Anthropic(credentials=ClaudeCodeCredentials())`."""

    def __init__(self, path=None):
        self._path = pathlib.Path(path) if path else default_credentials_path()

    def __call__(self, *, force_refresh=False):
        del force_refresh  # nothing to refresh ourselves - see module docstring
        oauth = self._read_oauth_block()

        expires_at_ms = oauth.get("expiresAt")
        if isinstance(expires_at_ms, (int, float)) and expires_at_ms / 1000 < time.time():
            raise ClaudeCodeCredentialsError(
                f"Claude Code's access token in {self._path} looks expired - "
                "log in again in Claude Code (e.g. `/login`) to refresh it"
            )

        # expires_at=0 tells the SDK's TokenCache to call us again before
        # every request instead of caching our result - we already re-read
        # fresh above, so this just keeps the cache from going stale too.
        return AccessToken(token=oauth["accessToken"], expires_at=0)

    def _read_oauth_block(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError as e:
            raise ClaudeCodeCredentialsError(
                f"no Claude Code credentials file at {self._path} - log in with "
                "Claude Code first, or use ANTHROPIC_API_KEY / `ant auth login` "
                'instead (see README.md\'s "Authenticating Claude" section)'
            ) from e
        except (json.JSONDecodeError, OSError) as e:
            raise ClaudeCodeCredentialsError(f"couldn't read {self._path}: {e}") from e

        oauth = data.get("claudeAiOauth")
        if not isinstance(oauth, dict) or not oauth.get("accessToken"):
            raise ClaudeCodeCredentialsError(
                f"{self._path} doesn't look like a Claude Code credentials file "
                "(missing claudeAiOauth.accessToken)"
            )
        return oauth
