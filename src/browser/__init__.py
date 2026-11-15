"""
AutoBot v2 Browser & Computer Use Module.

Exports:
- BrowserManager: Manages Chromium browser lifecycle, anti-bot args, and session persistence.
- LinkedInNavigator: Automates LinkedIn authentication, search filtering, and job card extraction.
- EasyApplyActuator: Multi-step LinkedIn Easy Apply modal automation with RAG form filling.
- ExternalApplyActuator: Automation for third-party ATS career portals.
- BrowserBridge: High-level adapter bridging Playwright actuators directly to LangGraph nodes.
"""

from src.browser.base_backend import BrowserBackend
from src.browser.backends.chromium_backend import ChromiumBackend
from src.browser.backends.obscura_backend import ObscuraBackend
from src.browser.bridge import BrowserBridge
from src.browser.easy_apply_actuator import EasyApplyActuator
from src.browser.external_apply_actuator import ExternalApplyActuator
from src.browser.manager import BrowserManager
from src.browser.navigator import LinkedInNavigator

__all__ = [
    "BrowserBackend",
    "ChromiumBackend",
    "ObscuraBackend",
    "BrowserBridge",
    "BrowserManager",
    "EasyApplyActuator",
    "ExternalApplyActuator",
    "LinkedInNavigator",
]
