"""
Browser Backend implementations for AutoBot v2.2.
"""

from src.browser.backends.chromium_backend import ChromiumBackend
from src.browser.backends.obscura_backend import ObscuraBackend

__all__ = ["ChromiumBackend", "ObscuraBackend"]
