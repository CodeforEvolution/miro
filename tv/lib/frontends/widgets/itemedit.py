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

"""miro.frontends.widgets.itemedit -- dialog for editing and
metainformation about an item.
"""

from miro.gtcache import gettext as _
from miro.plat.frontends.widgets import widgetset
from miro.frontends.widgets.dialogs import MainDialog
from miro.frontends.widgets import dialogwidgets, widgetconst
from miro.dialogs import BUTTON_CANCEL, BUTTON_APPLY

import textwrap
import logging

def build_info(label, value):
    """Takes a label and a value and generates two labels.
    """
    lab = widgetset.Label(label)
    lab.set_color(widgetconst.DIALOG_NOTE_COLOR)
    lab2 = widgetset.Label(value)
    lab2.set_color(widgetconst.DIALOG_NOTE_COLOR)
    lab2.set_wrap(True)

    return lab, lab2, lambda x: x

def build_text_entry(key, label, value):
    """Takes a key, label, and value and generates a label, text entry
    and a handler.

    :param key: used as the key in the response dict
    :param label: the label the user sees
    :param value: the current value of this thing

    :returns: label widget, section widget, handler function
    """
    lab = widgetset.Label(label)
    entry = widgetset.TextEntry()
    entry.set_text(value)

    def handler(response_dict):
        if entry.get_text() != value:
            response_dict[key] = entry.get_text()

    return lab, entry, handler

def build_multiline_text_entry(key, label, value):
    """Takes a key, label, and value and generates a label, multiline
    text entry in a scroller, and a handler.

    :param key: used as the key in the response dict
    :param label: the label the user sees
    :param value: the current value of this thing

    :returns: label widget, section widget, handler function
    """
    lab = widgetset.Label(label)
    entry = widgetset.MultilineTextEntry()
    entry.set_text(value)
    scroller = widgetset.Scroller(False, True)
    scroller.set_has_borders(True)
    scroller.set_size_request(400, 100)
    scroller.add(entry)
    def handler(response_dict):
        if entry.get_text() != value:
            response_dict[key] = entry.get_text()

    return lab, scroller, handler

def build_radio(key, label, value, options):
    """Takes a key, label, value and list of (option label, option value)
    pairs and generates a radio button group, label and handler.

    :param key: used as the key in the response dict
    :param label: the label the user sees
    :param value: the current value of this thing
    :param options: list of (label, value) tuples one for each radio
                    button

    :returns: label widget, section widget, handler function
    """
    vbox = widgetset.VBox()

    lab = widgetset.Label(label)
    rbg = widgetset.RadioButtonGroup()
    option_buttons = []
    for option, option_value in options:
        butt = widgetset.RadioButton(option, rbg)
        option_buttons.append((butt, option_value))
        vbox.pack_start(butt)
        if option_value == value:
            butt.set_selected()

    def handler(response_dict):
        selected = rbg.get_selected()
        for rb, rbv in option_buttons:
            if rb == selected:
                if rbv != value:
                    response_dict[key] = rbv
                break

    return lab, vbox, handler

def _run_dialog(iteminfo):
    """Creates and launches the item edit dialog.  This
    dialog waits for the user to press "Apply" or "Cancel".

    Returns a dict of new name -> value.
    """
    window = MainDialog(_('Edit Item'), "")
    try:
        try:
            window.add_button(BUTTON_APPLY.text)
            window.add_button(BUTTON_CANCEL.text)

            sections = []

            sections.append(build_text_entry(
                "name", _("Title:"), iteminfo.name))
            sections.append(build_multiline_text_entry(
                "description", _("Description:"), iteminfo.description))
            sections.append(build_radio(
                "file_type", _("Media type:"),
                iteminfo.file_type,
                [(_("Video"), u"video"),
                 (_("Music"), u"audio"),
                 (_("Misc"), u"other")]))

            # we do this to force wrapping at 50 characters
            sections.append(build_info(
                _("Path:"), "\n".join(textwrap.wrap(iteminfo.video_path, 50))))

            grid = dialogwidgets.ControlGrid()
            
            for lab, sec, handler in sections:
                vbox = widgetset.VBox()
                vbox.pack_start(lab, expand=True, padding=2)
                grid.pack(vbox, grid.ALIGN_RIGHT)
                grid.pack(sec, grid.FILL)
                grid.end_line(spacing=8)

            window.set_extra_widget(grid.make_table())

            response = window.run()

            response_dict = {}
            if response == 0:
                for lab, sec, handler in sections:
                    handler(response_dict)
            return response_dict

        except StandardError:
            logging.exception("itemedit threw exception.")
    finally:
        window.destroy()
        
def run_dialog(iteminfo):
    """Creates and launches the "edit item" dialog.
    
    Returns a response dict of name -> value pairs that need to
    be updated.
    """
    response_dict = _run_dialog(iteminfo)

    return response_dict
