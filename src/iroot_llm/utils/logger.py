#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import os
import warnings
from contextlib import suppress

from .tqdm import TqdmStream


def formatwarning(msg, category, filename, lineno, line=None):
    # print(f"{message=} {category=} {filename=} {lineno=} {line=}")
    return f"[[bold yellow]{category.__name__}[/bold yellow]] {msg}"


def setup_logger(capture_warning: bool = True, **kwargs):
    try:
        # new rich handler
        from rich.logging import RichHandler

        fmt = "[[bold blue]%(module)s:%(funcName)s@%(lineno)d[/bold blue]] %(message)s"
        kwargs.setdefault("rich_tracebacks", True)
        kwargs.setdefault("markup", True)
        kwargs.setdefault("show_path", False)
        stream = RichHandler(**kwargs)
    except ImportError:
        fmt = "[%(levelname)s][%(asctime)s][%(module)s:%(funcName)s@%(lineno)d] %(message)s"
        stream = TqdmStream()
        with suppress(ImportError):
            from colorlog import ColoredFormatter

            stream.setFormatter(
                ColoredFormatter(
                    """[%(log_color)s%(levelname)s%(reset)s][%(blue)s%(asctime)s%(reset)s]"""
                    """[%(red)s%(module)s:%(funcName)s@%(lineno)d%(reset)s] %(message)s"""
                )
            )
    level = os.environ.get("LOGLEVEL", "INFO").upper()
    try:
        logging.basicConfig(
            format=fmt, level=level, handlers=[stream], force=True, datefmt="[%X]"
        )
    except ValueError:
        logging.basicConfig(format=fmt, level=level, handlers=[stream], datefmt="%X")

    # warning handler
    logging.captureWarnings(capture_warning)
    warnings.formatwarning = formatwarning
    # logging.getLogger('py.warnings').addHandler(stream)
    # warnings.show
    # warnings.showwarning = showwarning

    # remove extra packages logger handler
    for name in ("lightning",):
        _logger = logging.getLogger(name)
        _logger.handlers.clear()
        # _logger.(fmt)
        # _logger.addHandler(stream)


def showwarning(message, category, filename, lineno, file=None, line=None):
    if file:
        raise ValueError(file)  # exercise for the reader
    message = warnings.formatwarning(message, category, filename, lineno, line)
    # for module_name, module in sys.modules.items():
    #     module_path = getattr(module, "__file__", None)
    #     if module_path and os.path.samefile(module_path, filename):
    #         break
    # else:
    module_name = os.path.splitext(os.path.split(filename)[1])[0]
    logger = logging.getLogger(module_name)
    # TODO: handle when not logger.hasHandlers()
    logger.warning(message, stacklevel=2)
