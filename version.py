"""
Version and metadata information for the LLM API Connector service.
"""

__version__ = "1.4.0"
__service_name__ = "LLM API Connector"
__description__ = "Service for interfacing with LLM providers (OpenAI, Azure, etc.)"
__author__ = "WoPeD Team"
__license__ = "See LICENSE file"

# Build information (can be populated during CI/CD)
__build_date__ = None
__git_commit__ = None

# Legacy: __api_version__ was intended as a URL prefix (e.g. /v1/...) but was
# never imported or used anywhere in the codebase. Routes have no /v1 prefix
# and get_version_info() is never called. Kept here for reference only.
# __api_version__ = "v1"


def get_version_info():
    """
    Returns a dictionary with version and metadata information.
    """
    return {
        "version": __version__,
        "service_name": __service_name__,
        "description": __description__,
        "author": __author__,
        "license": __license__,
        # "api_version": __api_version__,  # legacy, see comment above
        "build_date": __build_date__,
        "git_commit": __git_commit__,
    }
