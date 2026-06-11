from .service import SessionService

# Router is defined in api/sessions.py; this module re-exports the service
# for convenience so other modules can import from sessions.router without
# knowing the internal layout.
__all__ = ["SessionService"]
