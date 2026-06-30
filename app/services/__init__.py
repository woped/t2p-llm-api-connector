"""Service package marker.

Keep this module side-effect free so importing submodules like
`app.services.async_jobs` does not eagerly import heavy provider SDKs.
"""

__all__ = []
