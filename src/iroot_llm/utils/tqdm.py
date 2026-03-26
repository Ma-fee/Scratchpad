#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging

from tqdm import tqdm as _tqdm

# from unittest import mock

__TQDM_DEFAULTS = dict(disable=None, dynamic_ncols=True, leave=False, mininterval=1)
_tqdm.__init__.__default_kwargs__ = __TQDM_DEFAULTS
# patch("tqdm.tqdm.__init__", new=partial(tqdm, **__TQDM_DEFAULTS)).start()

try:
    from tqdm.rich import tqdm, trange
except ImportError:
    from tqdm import tqdm, trange


class TqdmStream(logging.StreamHandler):
    def __init__(self):
        super().__init__()

    def emit(self, record):
        msg = self.format(record)
        tqdm.write(msg)


__all__ = ["tqdm", "trange", "TqdmStream"]
