# Miro - an RSS based video player application
# Copyright (C) 2005-2010 Participatory Culture Foundation
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

import os
import glob
import logging

from objc import pathForFramework, loadBundleFunctions
from Foundation import *
from QTKit import *

from miro import app
from miro import prefs
from miro import player
from miro import iso639
from miro.plat import utils
from miro.plat import bundle
from miro.plat import qtcomp
from miro.plat import script_codes
from miro.plat.frontends.widgets import threads
from miro.plat.frontends.widgets.helpers import NotificationForwarder
from miro.util import copy_subtitle_file

###############################################################################

qt_framework = pathForFramework("QuickTime.framework")
qt_bundle = NSBundle.bundleWithPath_(qt_framework)
loadBundleFunctions(qt_bundle, globals(), (('GetMediaLanguage', 's^^{}'),))

###############################################################################

def register_components():
    bundlePath = bundle.getBundlePath()
    componentsDirectoryPath = os.path.join(bundlePath, 'Contents', 'Components')
    components = glob.glob(os.path.join(componentsDirectoryPath, '*.component'))
    for component in components:
        cmpName = os.path.basename(component)
        stdloc1 = os.path.join("/", "Library", "Quicktime", cmpName)
        stdloc2 = os.path.join("/", "Library", "Audio", "Plug-Ins", "Components", cmpName)
        if not os.path.exists(stdloc1) and not os.path.exists(stdloc2):
            ok = qtcomp.register(component.encode('utf-8'))
            if ok:
                logging.info('Successfully registered embedded component: %s' % cmpName)
            else:
                logging.warn('Error while registering embedded component: %s' % cmpName)
        else:
            logging.info('Skipping embedded %s registration, already installed.' % cmpName)

###############################################################################

class WarmupProgressHandler(NSObject):
    def init(self):
        self = super(WarmupProgressHandler, self).init()
        self.complete = False
        return self
    def loadStateChanged_(self, notification):
        self.handleLoadStateForMovie_(notification.object())
    def handleInitialLoadStateForMovie_(self, movie):
        load_state = movie.attributeForKey_(QTMovieLoadStateAttribute).longValue()
        if load_state < QTMovieLoadStateComplete:
            NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
                warmup_handler, 
                'loadStateChanged:', 
                QTMovieLoadStateDidChangeNotification, 
                warmup_movie)
        else:
            self.handleLoadStateForMovie_(movie)
    def handleLoadStateForMovie_(self, movie):
        load_state = movie.attributeForKey_(QTMovieLoadStateAttribute).longValue()
        if load_state == QTMovieLoadStateComplete:
            logging.info("QuickTime warm up complete")
            NSNotificationCenter.defaultCenter().removeObserver_(self)
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                10, self, 'releaseWarmupMovie:', None, False)
            self.complete = True
    def releaseWarmupMovie_(self, timer):
        logging.info("Releasing warmup movie.")
        global warmup_movie
        del warmup_movie

warmup_handler = WarmupProgressHandler.alloc().init()
warmup_movie = None

def warm_up():
    logging.info('Warming up QuickTime')
    rsrcPath = bundle.getBundleResourcePath()

    attributes = NSMutableDictionary.dictionary()
    attributes['QTMovieFileNameAttribute'] = os.path.join(rsrcPath, 'warmup.mov')
    attributes['QTMovieOpenAsyncRequiredAttribute'] = True
    attributes['QTMovieDelegateAttribute'] = None

    global warmup_movie
    warmup_movie, error = QTMovie.movieWithAttributes_error_(attributes, None)
    
    if error is not None:
        logging.warn("QuickTime Warm Up failed: %s" % error)
    else:
        warmup_handler.handleInitialLoadStateForMovie_(warmup_movie)

###############################################################################

def qttime2secs(qttime):
    timeScale = qttimescale(qttime)
    if timeScale == 0:
        return 0.0
    timeValue = qttimevalue(qttime)
    return timeValue / float(timeScale)

def qttimescale(qttime):
    if isinstance(qttime, tuple):
        return qttime[1]
    else:
        return qttime.timeScale

def qttimevalue(qttime):
    if isinstance(qttime, tuple):
        return qttime[0]
    else:
        return qttime.timeValue

###############################################################################
# The QTMediaTypeSubtitle and QTMediaTypeClosedCaption media types are only
# available in OS X 10.6 so we emulate them if they aren't defined.

try:
    dummy = QTMediaTypeSubtitle
except:
    QTMediaTypeSubtitle = u'sbtl'

try:
    dummy = QTMediaTypeClosedCaption
except:
    QTMediaTypeClosedCaption = u'clcp'

###############################################################################

class Player(player.Player):

    def __init__(self, supported_media_types):
        player.Player.__init__(self)
        self.supported_media_types = supported_media_types
        self.movie_notifications = None
        self.movie = None
        self.item_info = None

    def reset(self):
        threads.warn_if_not_on_main_thread('quicktime.Player.reset')
        if self.movie_notifications is not None:
            self.movie_notifications.disconnect()
        self.movie_notifications = None
        self.movie = None
        self.item_info = None

    def set_item(self, item_info, callback, errback, force_subtitles=False):
        threads.warn_if_not_on_main_thread('quicktime.Player.set_item')
        qtmovie = self.get_movie_from_file(item_info.video_path)
        self.reset()
        if qtmovie is not None:
            self.movie = qtmovie
            self.item_info = item_info
            self.movie_notifications = NotificationForwarder.create(self.movie)
            self.movie_notifications.connect(self.handle_movie_notification, QTMovieDidEndNotification)
            self.setup_subtitles(force_subtitles)
            callback()
        else:
            errback()

    def get_movie_from_file(self, path):
        osfilename = utils.filename_type_to_os_filename(path)
        try:
            url = NSURL.URLWithString_(path.urlize())
        except AttributeError:
            url = NSURL.fileURLWithPath_(osfilename)
        attributes = NSMutableDictionary.dictionary()
        # XXX bz:15481.  This shouldn't be synchronous.
        no = NSNumber.alloc().initWithBool_(NO)
        attributes['QTMovieURLAttribute'] = url
        attributes['QTMovieOpenAsyncOKAttribute'] = no
        qtmovie, error = QTMovie.movieWithAttributes_error_(attributes, None)
        if qtmovie is None or error is not None:
            return None
        if not self.can_open_file(qtmovie):
            return None
        return qtmovie

    def can_open_file(self, qtmovie):
        threads.warn_if_not_on_main_thread('quicktime.Player.can_open_file')
        can_open = False
        duration = utils.qttimevalue(qtmovie.duration())
        
        if qtmovie is not None and duration > 0:
            allTracks = qtmovie.tracks()
            if len(qtmovie.tracks()) > 0:
                # Make sure we have at least one track with a non zero length
                allMedia = [track.media() for track in allTracks]
                for media in allMedia:
                    mediaType = media.attributeForKey_(QTMediaTypeAttribute)
                    mediaDuration = utils.qttimevalue(media.attributeForKey_(QTMediaDurationAttribute).QTTimeValue())
                    if mediaType in self.supported_media_types and mediaDuration > 0:
                        can_open = True
                        break

        return can_open

    def setup_subtitles(self, force_subtitles):
        if app.config.get(prefs.ENABLE_SUBTITLES) or force_subtitles:
            enabled_tracks = self.get_all_enabled_subtitle_tracks()
            if len(enabled_tracks) == 0:
                tracks = self.get_subtitle_tracks()
                if len(tracks) > 0:
                    self.enable_subtitle_track(tracks[0])
            elif len(enabled_tracks) > 1:
                track_id = enabled_tracks[-1].attributeForKey_(QTTrackIDAttribute)
                self.disable_subtitles()
                self.enable_subtitle_track(track_id)
        else:
            self.disable_subtitles()

    def get_subtitle_tracks(self):
        tracks = list()
        if self.movie is not None:
            for track in self.movie.tracks():
                if self.is_subtitle_track(track):
                    media = track.media().quickTimeMedia()
                    lang = GetMediaLanguage(media)
                    display_name = track.attributeForKey_(QTTrackDisplayNameAttribute)
                    if lang == 32767:    # 32764 = langUndefined
                        name = display_name
                    else:
                        lang_code = script_codes.map_to_two_letters_code(lang)
                        lang_info = iso639.find(lang_code)
                        if lang_info is None:
                            name = display_name
                        else:
                            name = lang_info["name"]
                    if name != display_name:
                        name = "%s (%s)" % (name, display_name)
                    is_enabled = track.attributeForKey_(QTTrackEnabledAttribute) == 1
                    track_id = track.attributeForKey_(QTTrackIDAttribute)
                    tracks.append((track_id, name, is_enabled))
        return tracks

    def _find_track(self, key, value):
        if self.movie is not None:
            for track in self.movie.tracks():
                if self.is_subtitle_track(track):
                    if track.attributeForKey_(key) == value:
                        return track
        return None

    def _find_all_tracks(self, key, value):
        tracks = list()
        if self.movie is not None:
            for track in self.movie.tracks():
                if self.is_subtitle_track(track):
                    if track.attributeForKey_(key) == value:
                        tracks.append(track)
        return tracks

    def get_enabled_subtitle_track(self):
        return self._find_track(QTTrackEnabledAttribute, 1)

    def get_all_enabled_subtitle_tracks(self):
        return self._find_all_tracks(QTTrackEnabledAttribute, 1)

    def get_subtitle_track_by_name(self, name):
        return self._find_track(QTTrackDisplayNameAttribute, name)

    def get_subtitle_track_by_id(self, track_id):
        return self._find_track(QTTrackIDAttribute, track_id)

    def is_subtitle_track(self, track):
        layer = track.attributeForKey_(QTTrackLayerAttribute)
        media_type = track.attributeForKey_(QTTrackMediaTypeAttribute)
        return (layer == -1 and media_type == QTMediaTypeVideo) or media_type in [QTMediaTypeSubtitle, QTMediaTypeClosedCaption]

    def enable_subtitle_track(self, track_id):
        current = self.get_enabled_subtitle_track()
        if current is not None:
            current.setAttribute_forKey_(0, QTTrackEnabledAttribute)
        to_enable = self.get_subtitle_track_by_id(track_id)
        if to_enable is not None:
            to_enable.setAttribute_forKey_(1, QTTrackEnabledAttribute)

    def disable_subtitles(self):
        track = self.get_enabled_subtitle_track()
        if track is not None:
            track.setAttribute_forKey_(0, QTTrackEnabledAttribute)

    def select_subtitle_file(self, sub_path, handle_successful_select):
        def handle_ok():
            handle_successful_select()
        def handle_err():
            app.playback_manager.stop()
        copy_subtitle_file(sub_path, self.item_info.video_path)
        self.set_item(self.item_info, handle_ok, handle_err, True)

    def select_subtitle_encoding(self, encoding):
        # FIXME - set the subtitle encoding in quicktime
        pass

    def set_volume(self, volume):
        if self.movie:
            self.movie.setVolume_(volume)

    def get_elapsed_playback_time(self):
        qttime = self.movie.currentTime()
        return utils.qttime2secs(qttime)

    def get_total_playback_time(self):
        if self.movie is None:
            return 0
        qttime = self.movie.duration()
        return utils.qttime2secs(qttime)

    def skip_forward(self):
        current = self.get_elapsed_playback_time()
        duration = self.get_total_playback_time()
        pos = min(duration, current + 30.0)
        self.seek_to(pos / duration)

    def skip_backward(self):
        current = self.get_elapsed_playback_time()
        duration = self.get_total_playback_time()
        pos = max(0, current - 15.0)
        self.seek_to(pos / duration)

    def seek_to(self, position):
        qttime = self.movie.duration()
        if isinstance(qttime, tuple):
            qttime = (qttime[0] * position, qttime[1], qttime[2])
        else:
            qttime.timeValue = qttime.timeValue * position
        self.movie.setCurrentTime_(qttime)

    def play_from_time(self, resume_time=0):
        self.seek_to(resume_time / self.get_total_playback_time())
        self.play()

    def set_playback_rate(self, rate):
        self.movie.setRate_(rate)

    def handle_movie_notification(self, notification):
        if notification.name() == QTMovieDidEndNotification and not app.playback_manager.is_suspended:
            app.playback_manager.on_movie_finished()

###############################################################################
