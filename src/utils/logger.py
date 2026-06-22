import logging
import sys
from src.config import settings

# ANSI color codes
GREY = "\x1b[38;20m"
YELLOW = "\x1b[33;20m"
RED = "\x1b[31;20m"
BOLD_RED = "\x1b[31;1m"
BLUE = "\x1b[36;20m"
GREEN = "\x1b[32;20m"
RESET = "\x1b[0m"

class CustomFormatter(logging.Formatter):
    format_str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    FORMATS = {
        logging.DEBUG: GREY + format_str + RESET,
        logging.INFO: BLUE + format_str + RESET,
        logging.WARNING: YELLOW + format_str + RESET,
        logging.ERROR: RED + format_str + RESET,
        logging.CRITICAL: BOLD_RED + format_str + RESET
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
        return formatter.format(record)

def setup_logger(name: str = "swarm") -> logging.Logger:
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers if setup_logger is called multiple times
    if logger.handlers:
        return logger

    logger.setLevel(settings.LOG_LEVEL)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(settings.LOG_LEVEL)
    ch.setFormatter(CustomFormatter())
    logger.addHandler(ch)

    return logger

# Export a default root logger
logger = setup_logger("swarm-root")
