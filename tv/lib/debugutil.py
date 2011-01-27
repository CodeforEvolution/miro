# Miro - an RSS based video player application
# Copyright (C) 2010, 2011
# Participatory Culture Foundation
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
#
# In addition, as a special exception, the copyright holders give
# permission to link the code of portions of this program with the OpenSSL
# library.
#
# You must obey the GNU General Public License in all respects for all of
# the code used other than OpenSSL. If you modify file(s) with this
# exception, you may extend this exception to your version of the file(s),
# but you are not obligated to do so. If you do not wish to do so, delete
# this exception statement from your version. If you delete this exception
# statement from all source files in the program, then also delete it here.

"""
This module contains a series of debugging functions that I keep
writing and finally got around to persisting to the code-base.

.. Note::

   These are literally thrown together based on what I needed at the
   time.  Feel free to adjust them for better functionality.
"""

import logging
import traceback
import time

def logwrap(fun):
    """Function decorator that wraps a function and logs when it
    starts and when it ends.

    Example::

        @logwrap
        def foo():
            pass
    """
    # don't wrap a wrapped function
    if fun.__name__ == "_wrapped_fun":
        return fun
    def _wrapped_fun(*args, **kwargs):
        name = "%s %s %s" % (time.time(), fun.__module__, fun.__name__)
        ret = None
        try:
            logging.info("START: %s", name)
            ret = fun(*args, **kwargs)
            return ret
        finally:
            logging.info("END:   %s ret: %s", name, ret)
    return _wrapped_fun

def instrument_class(klass):
    """Instruments a class wrapping all methods with logwrap.

    Example::

        class Foo:
            def bar(self):
                pass

        instrument_class(Foo)
    """
    for name in dir(klass):
        try:
            mem = klass.__dict__[name]
        except KeyError:
            continue
        if not callable(mem):
            continue
        setattr(klass, name, logwrap(mem))
