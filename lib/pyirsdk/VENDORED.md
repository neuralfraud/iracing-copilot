# Vendored: pyirsdk

This directory is a verbatim copy of [kutu/pyirsdk](https://github.com/kutu/pyirsdk)
(MIT licensed, see `LICENSE`), vendored at commit
`1abbd64dffdc74377c215ffc783a0458bd81e614` (2026-10-03) instead of pulled
from PyPI, so this project:

- doesn't depend on PyPI being reachable to install,
- can be modified directly if needed - e.g. extending the `IBT` class to
  also parse the `CarSetup` session-info section from recorded `.ibt`
  files, which upstream doesn't currently do (see the gap noted in this
  project's own README/commit history),
- pins to an exact, known-good version rather than "whatever `pip install
  pyirsdk` resolves to today."

Files here are otherwise untouched from upstream. If you modify `irsdk.py`,
note the change here (and consider upstreaming it) so a future re-vendor
doesn't silently clobber it.

`irsdk.py`'s own runtime dependency is `PyYAML`, listed in this project's
top-level `requirements.txt`.
