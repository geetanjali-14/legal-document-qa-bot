import logging
import sys


def setup_logging(debug: bool | None = None) -> logging.Logger:
    if debug is None:
        try:
            from app.core.config import settings
            debug = settings.DEBUG
        except Exception:
            debug = False

    level = logging.DEBUG if debug else logging.INFO
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger("legal_qa")
    root_logger.setLevel(level)
    if not root_logger.handlers:
        root_logger.addHandler(handler)
    root_logger.propagate = False

    return root_logger


logger = setup_logging()
