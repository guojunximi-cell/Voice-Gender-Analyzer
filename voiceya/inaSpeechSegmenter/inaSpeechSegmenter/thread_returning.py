#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Mar 27 15:18:49 2018

@author: elechapt
"""

from threading import Thread
from typing import Any, Callable


class ThreadReturning(Thread):
    """
    Allow us to get the results from a thread
    """

    _args: tuple[Any, ...]
    _kwargs: dict[str, Any]
    _target: Callable

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._return: Any = None

    def run(self):
        if self._target is not None:
            self._return = self._target(*self._args, **self._kwargs)

    def join(self, timeout=None):
        super().join(timeout)
        return self._return
