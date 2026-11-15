"""
Abstract Browser Backend Interface for AutoBot v2.2.
Provides clean provider abstraction across Chromium (default) and Obscura (optional).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Union

from playwright.async_api import Browser, BrowserContext, Page, Playwright


class BrowserBackend(ABC):
    """Abstract interface defining the lifecycle and contract for browser backends."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Name identifier of the backend ('chromium' or 'obscura')."""
        pass

    @abstractmethod
    async def start(self) -> None:
        """Start or connect to the browser instance."""
        pass

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Check if the browser backend process and CDP endpoints are healthy."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Cleanly terminate browser processes, connections, and temporary state."""
        pass

    @property
    @abstractmethod
    def context(self) -> Optional[BrowserContext]:
        """Active Playwright BrowserContext."""
        pass

    @property
    @abstractmethod
    def page(self) -> Optional[Page]:
        """Active primary Page."""
        pass

    @property
    @abstractmethod
    def browser(self) -> Optional[Browser]:
        """Active Browser instance (if available)."""
        pass

    @property
    @abstractmethod
    def playwright(self) -> Optional[Playwright]:
        """Active Playwright manager instance."""
        pass

    @abstractmethod
    async def upload_file(self, page: Page, selector: str, file_path: Union[str, Path]) -> bool:
        """
        Upload file to a file input element with backend-appropriate mechanics
        (Playwright set_input_files with fallback to CDP DOM.setFileInputFiles).
        """
        pass
