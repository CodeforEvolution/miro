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

"""miro.plat.options -- Holds platform-specific command line options.
Most/all of these are set in the miro.real script.  The values here are
hopefully sane defaults.
"""

# these have no related prefs
shouldSyncX = False
frontend = 'html'
themeName = None
gconf_name = None
user_home = "~/"

from miro.prefs import Pref

class LinuxPref(Pref):
    def __init__(self, key, default, alias, helptext):
        Pref.__init__(self, key, default, False, None, None)
        self.alias = alias
        self.helptext = helptext

FFMPEG_BINARY = LinuxPref(
    key="ffmpegBinary",
    default="/usr/bin/ffmpeg",
    alias="ffmpeg",
    helptext="Absolute path for ffmpeg binary.")

FFMPEG2THEORA_BINARY = LinuxPref(
    key="ffmpeg2TheoraBinary",
    default="/usr/bin/ffmpeg2theora",
    alias="ffmpeg2theora",
    helptext="Absolute path for ffmpeg2theora binary.")

FIRST_TIME = LinuxPref(
    key="startupTasksDone",
    default=False,
    alias="firsttimestartup",
    helptext="If true, forces first time startup dialog to show.")

USE_RENDERER = LinuxPref(
    key="useRenderer",
    default=u"gstreamer",
    alias="renderer",
    helptext="Which renderer to use.  (gstreamer, ...)" )

GSTREAMER_IMAGESINK = LinuxPref(
    key="DefaultGstreamerImagesink",
    default="gconfvideosink",
    alias="gstreamer-imagesink",
    helptext="Which GStreamer image sink to use for video.  (autovideosink, ximagesink, xvimagesink, gconfvideosink, ...)")

GSTREAMER_AUDIOSINK = LinuxPref(
    key="DefaultGstreamerAudiosink",
    default="gconfaudiosink",
    alias="gstreamer-audiosink",
    helptext="Which GStreamer sink to use for audio.  (autoaudiosink, osssink, alsasink, gconfaudiosink, ...)")


SHOW_TRAYICON = Pref(
    key="showTrayicon",
    default=True,
    platformSpecific=False)

WINDOWS_ICON = Pref(
    key='windowsIcon',
    default=None,
    # this is platform specific, but if we set this to True then it
    # won't look up the value in the theme's app.config file
    platformSpecific=False)

# build a lookup for preferences by alias
PREFERENCES = {}
for mem in dir():
    p = locals()[mem]
    if isinstance(p, Pref) and hasattr(p, "alias"):
        PREFERENCES[p.alias] = p
