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

"""Defines the "remove feeds" dialog."""

import logging

from miro import app
from miro import prefs
from miro import util
from miro.plat.frontends.widgets import widgetset
from miro.frontends.widgets import widgetutil
from miro.frontends.widgets.dialogs import MainDialog
from miro.dialogs import BUTTON_CANCEL, BUTTON_REMOVE
from miro.gtcache import gettext_lazy as _
from miro.gtcache import ngettext

KEEP_ITEMS = "keep_items"

def run_dialog(channel_infos, downloaded_items, downloading_items,
               has_watched_feeds):
    """Displays the remove feeds dialog.
    """
    title = ngettext('Remove Podcast', 'Remove Podcasts', len(channel_infos))

    rc_window = MainDialog(title)
    try:
        try:
            v = widgetset.VBox(spacing=5)

            lab = widgetset.Label(ngettext(
                "Are you sure you want to remove this podcast:",
                "Are you sure you want to remove these podcasts:",
                len(channel_infos)
            ))
            lab.set_wrap(True)
            v.pack_start(widgetutil.align_left(lab))

            v2 = widgetset.VBox()
            lab_height = None
            for mem in channel_infos:
                lab_mem = widgetset.Label(util.clamp_text(mem.name, 40))
                if lab_height is None:
                    dummy, lab_height = lab_mem.get_size_request()
                v2.pack_start(widgetutil.align_left(lab_mem, left_pad=15))

            if len(channel_infos) > 5:
                scroller = widgetset.Scroller(False, True)
                scroller.set_has_borders(True)
                scroller.add(v2)
                scroller_width, scroller_height = scroller.get_size_request()
                if scroller_height == 0:
                    scroller.set_size_request(scroller_width,
                                              5 * (lab_height + 1))
                v2 = scroller
            v.pack_start(v2, padding=10)

            cbx_downloaded = None
            if downloaded_items:
                cbx_downloaded = widgetset.Checkbox(_(
                        "Keep items that have been downloaded in my library."))
                v.pack_start(widgetutil.align_left(
                        cbx_downloaded, bottom_pad=5))

            if has_watched_feeds:
                lab = widgetset.Label(_(
                    "Watched folders will be removed from the sidebar but "
                    "their contents will still appear in your library.  "
                    "You can stop watching watched folders completely "
                    "in the %(appname)s preference panel.",
                    {"appname": app.config.get(prefs.SHORT_APP_NAME)}
                ))
                lab.set_wrap(True)
                lab.set_size_request(390, -1)
                v.pack_start(widgetutil.align_left(lab, bottom_pad=5))

            if downloading_items:
                lab_downloading = widgetset.Label(ngettext(
                    "Are you sure you want to remove this podcast?  "
                    "The downloads currently in progress will be canceled.",
                    "Are you sure you want to remove these podcasts?  "
                    "The downloads currently in progress will be canceled.",
                    len(channel_infos)
                ))
                lab_downloading.set_wrap(True)
                lab_downloading.set_size_request(390, -1)
                v.pack_start(widgetutil.align_left(lab_downloading))

            rc_window.set_extra_widget(v)
            rc_window.add_button(BUTTON_REMOVE.text)
            rc_window.add_button(BUTTON_CANCEL.text)
            ret = rc_window.run()
            if ret == 0:
                # this is silly, but it sets us up for adding additional
                # bits later.
                ret = {KEEP_ITEMS: False}
                if downloaded_items:
                    ret[KEEP_ITEMS] = cbx_downloaded.get_checked()
                return ret
        except StandardError:
            logging.exception("removefeeds threw exception.")
    finally:
        rc_window.destroy()
