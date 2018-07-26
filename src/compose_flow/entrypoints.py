"""
Entrypoints module

Main console script entrypoints for the dc tool
"""
import logging
import logging.config
import sys

from compose_flow import errors

MIN_VERSION = (3, 6)
RUNTIME_VERSION = (sys.version_info.major, sys.version_info.minor)

if RUNTIME_VERSION < MIN_VERSION:
    sys.exit('Error: compose-flow runs on Python3.6+')

from . import settings
from .commands import ComposeFlow


def compose_flow():
    """
    Main entrypoint
    """
    logging.config.dictConfig(settings.LOGGING)

    try:
        response = ComposeFlow().run()
    except errors.NoSuchConfig as exc:
        response = f'Error: {exc}'

    sys.exit(response)
