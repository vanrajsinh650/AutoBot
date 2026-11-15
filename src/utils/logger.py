"""
Rich-powered logger for AutoBot.
Import `logger` and `console` from here everywhere.
"""
import logging
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

_theme = Theme({
    "info":    "bold cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error":   "bold red",
    "job":     "bold magenta",
    "skip":    "dim white",
    "agent":   "bold blue",
})

console = Console(theme=_theme)


def get_logger(name: str = "AutoBot", level: str = "INFO") -> logging.Logger:
    Path("logs").mkdir(exist_ok=True)
    log_file = Path("logs") / f"autobot_{datetime.now().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(console=console, rich_tracebacks=True, markup=True),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    return logging.getLogger(name)


logger = get_logger()
