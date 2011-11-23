# Miro - an RSS based video player application
# Copyright (C) 2005, 2006, 2007, 2008, 2009, 2010, 2011
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

"""miro.plat.renderers -- Classes that render video files."""

import logging
import traceback
import os
import os.path

from miro import app
from miro.plat import options


def get_renderer_list():
    d = os.path.dirname(__file__)
    contents = os.listdir(d)
    # FIXME - this sucks.  switch this to use extensions.
    contents = [m for m in contents if m.endswith("renderer.py")]
    contents = [m[:-11] for m in contents]
    return contents


def set_renderer(modname):
    """Attempt to set the video renderer."""

    logging.debug("set_renderer: trying to add %s", modname)
    try:
        pkg = __import__('miro.plat.renderers.' + modname)
        module = getattr(pkg.plat.renderers, modname)
        app.audio_renderer, app.video_renderer = module.make_renderers()
        app.get_item_type = module.get_item_type
        logging.info("set_renderer: successfully loaded %s", modname)
    except StandardError:
        if app.debugmode:
            logging.warn("set_renderer: couldn't load %s: %s", modname,
                         traceback.format_exc())
        else:
            logging.warn("set_renderer: couldn't load %s.  "
                         "run miro in debugmode for more details.", modname)
        raise


def init_renderer():
    """Initializes a video renderer for us to use.  This call will
    attempt to find a working renderer and set the global variables
    ``app.audio_renderer`` and ``app.video_renderer`` to renderers in
    that module.

    .. Note::

       Renderer modules have to be ``xxxxrenderer`` and ``xxxx`` shows
       up in the preferences.
    """
    r = app.config.get(options.USE_RENDERER)
    try:
        set_renderer("%srenderer" % r)
        return
    except StandardError:
        if app.debugmode:
            logging.exception("init_renderer: error when trying to load renderer")
        else:
            logging.warn("init_renderer: error when trying to load renderer.  "
                         "run miro in debugmode for more details.")
        logging.info("trying to use gstreamerrenderer")

    try:
        # try to add the gstreamer renderer if the preferences aren't
        # right
        set_renderer("gstreamerrenderer")
        return
    except StandardError:
        logging.exception("init_renderer: no valid renderer has been loaded")
    app.audio_renderer = None
    app.video_renderer = None
