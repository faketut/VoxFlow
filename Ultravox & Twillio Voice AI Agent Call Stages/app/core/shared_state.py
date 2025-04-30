"""
Shared state for the application.
This module contains shared state that needs to be accessed by multiple modules.
Keeping it here helps avoid circular import issues.
"""

# Global session store
sessions = {}
