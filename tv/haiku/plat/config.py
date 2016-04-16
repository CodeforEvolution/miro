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

"""miro.plat.config

This module implements configuration persistence for the haiku
platform.  Miro persists configuration preferences for the haiku platform
to a sqlite database file.

Preferences are listed in miro.pref and also miro.plat.options.
"""

import os
import logging
from miro import prefs
import sqlite3 as db
from miro.plat import options
from miro.plat import resources

con = db.connect('/boot/home/config/settings/Miro/miro-config.db')

def load():
       with con:
	
             cur = con.cursor() 

             cur.execute("SELECT * FROM Data")
    	
             data = cur.fetchall()
             con.commit()

             return data
             con.close()

def save(data):
       with con:
    
             cur = con.cursor()
             cur.execute("DROP TABLE IF EXISTS Data")
             cur.execute("CREATE TABLE Data(Key TEXT)")
             cur.execute("INSERT INTO Data VALUES(?)", data)

             con.commit()
             con.close()

def get(descriptor):
    value = descriptor.default

    if descriptor == prefs.MOVIES_DIRECTORY:
        value = os.path.expanduser(os.path.join(options.user_home,
                                                'Videos/Miro'))

    elif descriptor == prefs.NON_VIDEO_DIRECTORY:
        value = os.path.expanduser(os.path.join(options.user_home, 'Desktop'))

    elif descriptor == prefs.GETTEXT_PATHNAME:
        value = resources.path("../../locale")

    elif descriptor == prefs.RUN_AT_STARTUP:
        # Not necessary to run at startup by default.
	 return False

    elif descriptor == prefs.SUPPORT_DIRECTORY:
        value = os.path.expanduser(os.path.join(options.user_home, 'config/settings/Miro'))

    elif descriptor == prefs.ICON_CACHE_DIRECTORY:
        value = get(prefs.SUPPORT_DIRECTORY)
        value = os.path.join(value, 'icon-cache')

    elif descriptor == prefs.COVER_ART_DIRECTORY:
        value = get(prefs.SUPPORT_DIRECTORY)
        value = os.path.join(value, 'cover-art')

    elif descriptor == prefs.SQLITE_PATHNAME:
        value = get(prefs.SUPPORT_DIRECTORY)
        value = os.path.join(value, 'sqlitedb')

    elif descriptor == prefs.CRASH_PATHNAME:
        value = get(prefs.SUPPORT_DIRECTORY)
        value = os.path.join(value, 'crashes')

    elif descriptor == prefs.LOG_PATHNAME:
        value = get(prefs.SUPPORT_DIRECTORY)
        value = os.path.join(value, 'miro.log')

    elif descriptor == prefs.DOWNLOADER_LOG_PATHNAME:
        value = get(prefs.SUPPORT_DIRECTORY)
        value = os.path.join(value, 'miro-downloader.log')

    elif descriptor == prefs.HELPER_LOG_PATHNAME:
        value = get(prefs.SUPPORT_DIRECTORY)
        value = os.path.join(value, 'miro-helper.log')

#On Haiku, there is no system stored proxy configuration info.
    elif descriptor == prefs.HTTP_PROXY_ACTIVE:
        return False

    elif descriptor == prefs.HTTP_PROXY_HOST:
        return False

    elif descriptor == prefs.HTTP_PROXY_PORT:
        return False

    elif descriptor == prefs.HTTP_PROXY_AUTHORIZATION_ACTIVE:
        return False

    elif descriptor == prefs.HTTP_PROXY_AUTHORIZATION_USERNAME:
        return False

    elif descriptor == prefs.HTTP_PROXY_AUTHORIZATION_PASSWORD:
        return False

    elif descriptor == prefs.HTTP_PROXY_IGNORE_HOSTS:
        return False

    return value
