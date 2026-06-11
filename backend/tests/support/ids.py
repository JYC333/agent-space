"""Bootstrap IDs used by ``tests/conftest.py`` seed rows.

``db`` / ``client`` fixtures create a Space and User with these primary keys.
Factories and fixtures should treat them as the default tenant for tests that
do not care about isolation.
"""

PERSONAL_SPACE_ID = "personal"
DEFAULT_USER_ID = "default_user"
