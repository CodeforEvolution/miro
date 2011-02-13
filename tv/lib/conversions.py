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

import os
import re
import time
import Queue
import shutil
import logging
import tempfile
import threading
import subprocess
import errno

from glob import glob
from ConfigParser import SafeConfigParser, NoOptionError

from miro import app
from miro.download_utils import next_free_filename
from miro import eventloop
from miro import fileutil
from miro import item
from miro import models
from miro import util
from miro import prefs
from miro import signals
from miro import messages
from miro.gtcache import gettext as _
from miro.fileobject import FilenameType
from miro.plat import utils
from miro.plat import resources

NON_WORD_CHARS = re.compile(r"[^a-zA-Z0-9]+")


def get_conversions_folder():
    """Get the folder for video conversions.

    This method is safe to call from the frontend thread.
    """
    root = app.config.get(prefs.MOVIES_DIRECTORY)
    target_folder = os.path.join(root, "Converted")
    if not os.path.exists(target_folder):
        os.mkdir(target_folder)
    return target_folder


class ConverterInfo(object):
    """Holds the data for a specific conversion that allows us to
    convert to this target.
    """

    def __init__(self, name, parser):
        self.name = name
        self.mediatype = self._get_config_value(name, parser, "mediatype", {})
        self.identifier = NON_WORD_CHARS.sub("", name).lower()
        self.executable = self._get_config_value(name, parser,
                                                 "executable", {})
        self.parameters = self._get_config_value(name, parser,
                                                 "parameters", {})
        self.extension = self._get_config_value(name, parser, "extension", {})
        self.screen_size = self._get_config_value(name, parser, "ssize", {})
        self.platforms = self._get_config_value(name, parser, "only_on",
                                                {'only_on': None})
        self.displayname = _(
            "%(name)s (%(mediatype)s)",
            {"name": self.name, "mediatype": self.mediatype})

    def _get_config_value(self, section, parser, key, defaults):
        try:
            return parser.get(section, key)
        except NoOptionError:
            return defaults.get(key)


class ConverterManager(object):
    """Manages converter .conv files which define the various
    conversions that Miro knows how to do.

    Conversion definition files are defined in
    ``resources/conversions/`` in files ending with ``.conv``.  Files
    are in classic config file format with a [DEFAULT] section and a
    section for each conversion possibility.

    See ``resources/conversions/`` for examples.
    """
    def __init__(self):
        # list of (group, list of ConverterInfo items) items
        self.converters = []

        # maps converter_id to ConverterInfo object
        self.converter_map = {}

    def load_converters(self, path):
        """Loads converters from conv files in path and and populates
        ``self.converters`` and ``self.converter_map`` structures.

        :param path: a glob-bable path like ``/foo/bar/baz/*.conv``
        """
        platform = app.config.get(prefs.APP_PLATFORM)
        groups = glob(path)
        groups.sort()
        for group_definition in groups:
            parser = SafeConfigParser()
            definition_file = open(group_definition)
            try:
                parser.readfp(definition_file)
                defaults = parser.defaults()
                sections = parser.sections()
                group_converters = list()
                for section in sections:
                    converter_info = ConverterInfo(section, parser)
                    if ((converter_info.platforms is None
                         or platform in converter_info.platforms)):
                        ident = converter_info.identifier
                        self.converter_map[ident] = converter_info
                        group_converters.append(converter_info)
                group_converters.sort(key=lambda x: x.name)
                self.converters.append((defaults['name'], group_converters))
            finally:
                definition_file.close()

    def lookup_converter(self, converter_id):
        """Looks up and returns a ConverterInfo object by id.

        :param converter_id: the id of the converter to lookup

        :returns: ConverterInfo

        :raises KeyError: if the converter doesn't exist
        """
        return self.converter_map[converter_id]

    def get_converters(self):
        return self.converters


class ConversionManager(signals.SignalEmitter):
    def __init__(self):
        signals.SignalEmitter.__init__(self,
                                       'thread-will-start',
                                       'thread-started',
                                       'thread-did-start',
                                       'begin-loop',
                                       'end-loop',
                                       'task-changed',
                                       'task-staged',
                                       'task-removed',
                                       'all-tasks-removed',
                                       )
        self.converters = ConverterManager()
        self.task_loop = None
        self.message_queue = Queue.Queue(-1)
        self.pending_tasks = list()
        self.running_tasks = list()
        self.finished_tasks = list()
        self.quit_flag = False

    def startup(self):
        self.converters.load_converters(resources.path('conversions/*.conv'))

    def shutdown(self):
        if self.task_loop is not None:
            self.cancel_all()
            self.task_loop.join()

    def cancel_all(self):
        self._enqueue_message("cancel_all")

    def cancel(self, key):
        self._enqueue_message("cancel", key=key)

    def clear_finished_conversions(self):
        self._enqueue_message("clear_all_finished")

    def schedule_staging(self, key):
        self._enqueue_message("stage_conversion", key=key)

    def clear_failed_task(self, key):
        self._enqueue_message("cancel", key=key)

    def clear_finished_task(self, key):
        self._enqueue_message("clear_finished", key=key)

    def fetch_tasks_list(self):
        self._enqueue_message("get_tasks_list")

    def get_converters(self):
        return self.converters.get_converters()

    def lookup_converter(self, converter_id):
        return self.converters.lookup_converter(converter_id)

    def start_conversion(self, converter_id, item_info, target_folder=None,
                         create_item=True):
        task = self._make_conversion_task(
            converter_id, item_info, target_folder, create_item)
        if ((task is not None
             and task.get_executable() is not None
             and not self._has_running_task(task.key)
             and not self._has_finished_task(task.key))):
            self._check_task_loop()
            self.pending_tasks.append(task)
            self._notify_task_added(task)

        return task

    def _enqueue_message(self, message, **kw):
        msg = {'message': message}
        msg.update(kw)
        self.message_queue.put(msg)

    def _make_conversion_task(self, converter_id, item_info, target_folder,
                              create_item):
        if converter_id == 'copy':
            return CopyConversionTask(item_info, target_folder, create_item)
        converter_info = self.converters.lookup_converter(converter_id)
        if converter_info.executable == 'ffmpeg':
            return FFMpegConversionTask(converter_info, item_info,
                                        target_folder, create_item)
        elif converter_info.executable == 'ffmpeg2theora':
            return FFMpeg2TheoraConversionTask(converter_info, item_info,
                                               target_folder, create_item)
        return None

    def _check_task_loop(self):
        if self.task_loop is None:
            self.quit_flag = False
            self.task_loop = threading.Thread(target=utils.thread_body,
                                              args=[self._loop],
                                              name="Conversion Loop")
            self.task_loop.setDaemon(True)
            self.task_loop.start()

    def _loop(self):
        self.emit('thread-will-start')
        self.emit('thread-started', threading.currentThread())
        self.emit('thread-did-start')
        while not self.quit_flag:
            self.emit('begin-loop')
            self._run_loop_cycle()
            self.emit('end-loop')
            time.sleep(0.5)
        logging.debug("Conversions manager thread loop finished.")
        self.task_loop = None

    def _run_loop_cycle(self):
        self._process_message_queue()

        notify_count = False
        max_concurrent_tasks = int(app.config.get(
                prefs.MAX_CONCURRENT_CONVERSIONS))
        if ((self.pending_tasks_count() > 0
             and self.running_tasks_count() < max_concurrent_tasks)):
            task = self.pending_tasks.pop()
            if not self._has_running_task(task.key):
                self.running_tasks.append(task)
                task.run()
                self._notify_task_changed(task)
                notify_count = True

        for task in list(self.running_tasks):
            if task.done_running():
                self._notify_task_changed(task)
                self.running_tasks.remove(task)
                self.finished_tasks.append(task)
                notify_count = True
                if task.is_finished():
                    self.schedule_staging(task.key)

        if notify_count:
            self._notify_tasks_count()

    def _process_message_queue(self):
        try:
            msg = self.message_queue.get_nowait()
        except Queue.Empty:
            return

        if msg['message'] == 'get_tasks_list':
            self._notify_tasks_list()

        elif msg['message'] == 'cancel':
            try:
                task = self._lookup_task(msg['key'])
            except KeyError:
                logging.warn("Couldn't find task for key %s", msg['key'])
                return
            if task.is_pending():
                task_list = self.pending_tasks
            elif task.is_running():
                task_list = self.running_tasks
            else:
                task_list = self.finished_tasks
            try:
                task_list.remove(task)
            except ValueError:
                logging.warn("Task not in list: %s", msg['key'])
            else:
                self._notify_task_removed(task)
                self._notify_tasks_count()
            task.interrupt()

        elif msg['message'] == 'clear_all_finished':
            for task in self.finished_tasks:
                self._notify_task_removed(task)
            self.finished_tasks = []
            self._notify_tasks_count()

        elif msg['message'] == 'clear_finished':
            try:
                task = self._lookup_task(msg['key'])
            except KeyError:
                logging.warn("Couldn't find task for key %s", msg['key'])
                return
            self.finished_tasks.remove(task)
            self._notify_task_removed(task)
            self._notify_tasks_count()

        elif msg['message'] == 'cancel_all':
            self._terminate()

        elif msg['message'] == 'stage_conversion':
            try:
                task = self._lookup_task(msg['key'])
            except KeyError:
                logging.warn("Couldn't find task for key %s", msg['key'])
                return
            source = task.temp_output_path
            destination, fp = next_free_filename(task.final_output_path)
            source_info = task.item_info
            conversion_name = task.get_display_name()
            if os.path.exists(source):
                self._move_finished_file(source, destination)
                if task.create_item:
                    _create_item_for_conversion(destination,
                                                source_info,
                                                conversion_name)
                if not task.temp_output_path.endswith('.tmp'):  # temp dir
                    clean_up(task.temp_output_path,
                             file_and_directory=True)
            else:
                task.error = _("Reason unknown--check log")
                self._notify_tasks_count()
            fp.close()
            self.emit('task-staged', task)

    def _move_finished_file(self, source, destination):
        try:
            shutil.move(source, destination)
        except OSError, e:
            if fileutil.is_windows_file_in_use_error(e):
                # File is in use on windows (#15312) try to copy
                # the file, then use fileutil.delete.
                shutil.copy(source, destination)
                fileutil.delete(source)
            else:
                raise

    def pending_tasks_count(self):
        return len(self.pending_tasks)

    def running_tasks_count(self):
        return len([t for t in self.running_tasks if not t.is_failed()])

    def failed_tasks_count(self):
        return len([t for t in self.running_tasks if t.is_failed()])

    def finished_tasks_count(self):
        return len(self.finished_tasks)

    def _lookup_task(self, key):
        # linear search here is inefficient, but with < 100
        # conversions should be fine
        for task in self.running_tasks:
            if task.key == key:
                return task
        for task in self.pending_tasks:
            if task.key == key:
                return task
        for task in self.finished_tasks:
            if task.key == key:
                return task
        raise KeyError("%s not found" % key)

    def _has_running_task(self, key):
        for task in self.running_tasks:
            if task.key == key:
                return True
        return False

    def _has_finished_task(self, key):
        for task in self.finished_tasks:
            if task.key == key:
                return True
        return False

    def _make_task_infos(self, task_list):
        return [messages.ConversionTaskInfo(t) for t in task_list]

    def _notify_tasks_list(self):
        message = messages.ConversionTasksList(
                self._make_task_infos(self.running_tasks),
                self._make_task_infos(self.pending_tasks),
                self._make_task_infos(self.finished_tasks))
        message.send_to_frontend()

    def _notify_task_added(self, task):
        info = messages.ConversionTaskInfo(task)
        message = messages.ConversionTaskCreated(info)
        message.send_to_frontend()

    def _notify_task_removed(self, task):
        self.emit('task-removed', task)
        info = messages.ConversionTaskInfo(task)
        message = messages.ConversionTaskRemoved(info)
        message.send_to_frontend()

    def _notify_all_tasks_removed(self):
        self.emit('all-tasks-removed')
        message = messages.AllConversionTaskRemoved()
        message.send_to_frontend()

    def _notify_task_changed(self, task):
        self.emit('task-changed', task)
        info = messages.ConversionTaskInfo(task)
        message = messages.ConversionTaskChanged(info)
        message.send_to_frontend()

    def _notify_tasks_count(self):
        running_count = self.running_tasks_count()
        other_count = (self.failed_tasks_count() + self.pending_tasks_count() +
                self.finished_tasks_count())
        message = messages.ConversionsCountChanged(running_count,
                other_count)
        message.send_to_frontend()

    def _terminate(self):
        if len(self.pending_tasks) > 0:
            logging.debug("Clearing pending conversion tasks...")
            self.pending_tasks = list()
        if len(self.running_tasks) > 0:
            logging.debug("Interrupting running conversion tasks...")
            for task in list(self.running_tasks):
                self.running_tasks.remove(task)
                task.interrupt()
        self._notify_all_tasks_removed()
        self._notify_tasks_count()
        self.quit_flag = True


def build_output_paths(item_info, target_folder, converter_info):
    """Returns final_output_path and temp_output_path.

    We base the temp path on temp filenames.
    We base the final path on the item title.
    """
    if target_folder is None:
        use_temp_dir = True
        target_folder = get_conversions_folder()
    else:
        use_temp_dir = False
    input_path = item_info.video_path
    basename = os.path.basename(input_path)

    title = utils.unicode_to_filename(item_info.name, target_folder).strip()
    if not title:
        title = basename

    if converter_info:
        target_name = "%s.%s.%s" % (title, converter_info.identifier,
                                    converter_info.extension)
    else:
        target_name = basename
    final_path = FilenameType(os.path.join(target_folder, target_name))

    if not use_temp_dir:
        # convert directly onto the device
        temp_path = final_path + '.tmp'
    else:
        temp_dir = FilenameType(tempfile.mkdtemp("miro-conversion"))
        temp_path = os.path.join(temp_dir, basename)

    return (final_path, temp_path)


def build_parameters(input_path, output_path, converter_info):
    """Performs the substitutions on the converter_info parameters
    and returns a list of arguments.

    :param input_path: absolute path of the file to convert
    :param output_path: absolute path of output file
    :param converter_info: ConverterInfo object

    :returns: list of arguments
    """
    def substitute(param):
        if param == "{input}":
            return input_path
        elif param == "{output}":
            return output_path
        elif param == "{ssize}":
            return converter_info.screen_size
        return param
    return [substitute(p) for p in converter_info.parameters.split()]


def clean_up(temp_file, file_and_directory=False, attempts=0):
    if attempts > 5:
        return
    if os.path.exists(temp_file):
        try:
            os.remove(temp_file)
        except EnvironmentError, e:
            logging.debug("clean_up: %s kicked up while removing %s",
                          e, temp_file)
            timeout = 1.0 * attempts
            eventloop.add_timeout(
                timeout, clean_up, "conversion clean_up attempt",
                (temp_file, file_and_directory, attempts + 1))

    if file_and_directory:
        path = os.path.dirname(temp_file)
        if os.path.exists(path):
            try:
                os.rmdir(path)
            except EnvironmentError, e:
                logging.debug("clean_up: %s kicked up while removing %s",
                              e, path)
                timeout = 1.0 * attempts
                eventloop.add_timeout(
                    timeout, clean_up, "conversion clean_up attempt",
                    (temp_file, file_and_directory, attempts + 1))


class ConversionTask(object):
    def __init__(self, converter_info, item_info, target_folder,
                 create_item):
        self.item_info = item_info
        self.converter_info = converter_info
        self.input_path = item_info.video_path
        self.final_output_path, self.temp_output_path = build_output_paths(
            item_info, target_folder, converter_info)
        self.create_item = create_item

        logging.debug("temp_output_path: %s  final_output_path: %s",
                      self.temp_output_path, self.final_output_path)

        self.key = "%s->%s" % (self.input_path, self.final_output_path)
        self.thread = None
        self.duration = None
        self.progress = 0
        self.log_path = None
        self.log_file = None
        self.process_handle = None
        self.error = None
        self.start_time = time.time()

    def get_executable(self):
        raise NotImplementedError()

    def get_parameters(self):
        raise NotImplementedError()

    def get_display_name(self):
        return self.converter_info.displayname

    def run(self):
        self.progress = 0
        self.thread = threading.Thread(target=utils.thread_body,
                                       args=[self._loop],
                                       name="Conversion Task")
        self.thread.setDaemon(True)
        self.thread.start()

    def get_eta(self):
        """Calculates the eta for this conversion to be completed.

        :returns: None if progress is <= 0, otherwise returns number
            of seconds until this is complete
        """
        if self.progress <= 0:
            return None

        progress = self.progress * 100
        duration = time.time() - self.start_time
        time_per_percent = duration / progress
        return int(time_per_percent * (100 - progress))

    def is_pending(self):
        return self.thread is None

    def is_running(self):
        return self.thread is not None and self.thread.isAlive()

    def done_running(self):
        return self.thread is not None and not self.thread.isAlive()

    def is_finished(self):
        return self.done_running() and not self.is_failed()

    def is_failed(self):
        return (self.error or
                (self.process_handle is not None and
                 self.process_handle.returncode is not None and
                 self.process_handle.returncode != 0))

    def _loop(self):
        executable = self.get_executable()
        args = self.get_parameters()
        self._start_logging(executable, args)

        args.insert(0, executable)

        logging.debug("Conversion: (%s)", " ".join(args))

        kwargs = {"bufsize": 1,
                  "stdout": subprocess.PIPE,
                  "stderr": subprocess.STDOUT,
                  "stdin": subprocess.PIPE,
                  "startupinfo": util.no_console_startupinfo()}
        if os.name != "nt":
            kwargs["close_fds"] = True

        try:
            self.process_handle = subprocess.Popen(args, **kwargs)
            self.process_output(line_reader(self.process_handle.stdout))

        except OSError, ose:
            if ose.errno == errno.ENOENT:
                self.error = _("%(program)s does not exist.",
                               {"program": self.get_executable()})
            else:
                logging.exception("Exception in Popen: %s %s", args, kwargs)

        finally:
            self._stop_logging(self.progress < 1.0)
            if self.is_failed():
                conversion_manager._notify_tasks_count()

    def process_output(self, lines_generator):
        """Takes a function that's a generator of lines, iterates
        through the lines and checks for progress and errors.
        """
        for line in lines_generator():
            old_progress = self.progress

            line = line.strip()
            self._log_progress(line)

            error = self.check_for_errors(line)
            if error:
                self.error = error
                break

            self.progress = self.monitor_progress(line)
            if self.progress >= 1.0:
                self.progress = 1.0
                break

            if old_progress != self.progress:
                self._notify_progress()

    def _start_logging(self, executable, params):
        log_folder = os.path.dirname(app.config.get(prefs.LOG_PATHNAME))
        self.log_path = os.path.join(log_folder,
                                     "conversion-%d-to-%s.log" % (
                self.item_info.id, self.converter_info.identifier))
        self.log_file = file(self.log_path, "w")
        self._log_progress("STARTING CONVERSION")
        self._log_progress("-> Item: %s" % util.stringify(self.item_info.name))
        self._log_progress("-> Converter used: %s" % self.converter_info.name)
        self._log_progress("-> Executable: %s" % executable)
        self._log_progress("-> Parameters: %s" % ' '.join(params))
        self._log_progress("")

    def _log_progress(self, line):
        if not self.log_file.closed:
            self.log_file.write(line + "\n")
        else:
            logging.debug("conversion file closed: %s", line)

    def _stop_logging(self, keep_file=False):
        if not self.log_file.closed:
            self.log_file.flush()
            self.log_file.close()
        self.log_file = None
        if not keep_file:
            clean_up(self.log_path)
            self.log_path = None

    def _notify_progress(self):
        conversion_manager._notify_task_changed(self)

    def interrupt(self):
        if hasattr(self.process_handle, "pid"):
            logging.info("killing conversion task %d", self.process_handle.pid)
            utils.kill_process(self.process_handle.pid)
            if not self.temp_output_path.endswith('.tmp'):  # temp file
                if (os.path.exists(self.temp_output_path) and
                    self.progress < 1.0):
                    clean_up(self.temp_output_path, file_and_directory=True)


def line_reader(handle):
    """Builds a line reading generator for the given handle.  This
    generator breaks on empty strings, \\r and \\n.

    This a little weird, but it makes it really easy to test error
    checking and progress monitoring.
    """
    def _readlines():
        chars = []
        c = handle.read(1)
        while c:
            if c in ["", "\r", "\n"]:
                yield "".join(chars)
                chars = []
            else:
                chars.append(c)
            c = handle.read(1)
    return _readlines


class CopyConversionTask(ConversionTask):
    def __init__(self, item_info, target_folder, create_item):
        ConversionTask.__init__(self, None, item_info, target_folder,
                                create_item)

    def get_executable(self):
        # never actually executed
        return "copy"

    def get_display_name(self):
        return _("Copy")

    def run(self):
        shutil.copyfile(self.input_path, self.temp_output_path)
        self.progress = 1

    def is_pending(self):
        return not bool(self.progress)

    def is_running(self):
        # never running, since running is basically a no-op
        return False

    def done_running(self):
        return bool(self.progress)


class FFMpegConversionTask(ConversionTask):
    DURATION_RE = re.compile(r'Duration: (\d\d):(\d\d):(\d\d)\.(\d\d)'
                             '(, start:.*)?(, bitrate:.*)?')
    PROGRESS_RE = re.compile(r'(?:frame=.* fps=.* q=.* )?size=.* time=(.*) '
                             'bitrate=(.*)')
    LAST_PROGRESS_RE = re.compile(r'frame=.* fps=.* q=.* Lsize=.* time=(.*) '
                                  'bitrate=(.*)')

    def get_executable(self):
        return utils.get_ffmpeg_executable_path()

    def get_parameters(self):
        default_parameters = build_parameters(
            self.input_path, self.temp_output_path, self.converter_info)
        # insert -strict experimental
        default_parameters.insert(0, 'experimental')
        default_parameters.insert(0, '-strict')
        return utils.customize_ffmpeg_parameters(default_parameters)

    def check_for_errors(self, line):
        if line.startswith("Unknown"):
            return line

        if line.startswith("Error"):
            if line.startswith("Error while decoding stream"):
                return
            return line

    def monitor_progress(self, line):
        if self.duration is None:
            match = FFMpegConversionTask.DURATION_RE.match(line)
            if match is not None:
                hours = match.group(1)
                minutes = match.group(2)
                seconds = match.group(3)
                self.duration = (
                    (int(hours) * 60 * 60) +
                    (int(minutes) * 60) +
                    int(seconds))
        else:
            match = FFMpegConversionTask.PROGRESS_RE.match(line)
            if match is not None:
                return float(match.group(1)) / self.duration
            match = FFMpegConversionTask.LAST_PROGRESS_RE.match(line)
            if match is not None:
                return 1.0
        return self.progress


class FFMpeg2TheoraConversionTask(ConversionTask):
    DURATION_RE = re.compile(r'f2t ;duration: ([^;]*);')

    PROGRESS_RE1 = re.compile(r'\{"duration":(.*), "position":(.*), '
                              '"audio_kbps":.*, "video_kbps":.*, '
                              '"remaining":.*\}')
    RESULT_RE1 = re.compile(r'\{"result": "(.*)"\}')

    PROGRESS_RE2 = re.compile(r'f2t ;position: ([^;]*);')
    RESULT_RE2 = re.compile(r'f2t ;result: ([^;]*);')

    def __init__(self, converter_info, item_info, target_folder, create_item):
        ConversionTask.__init__(self, converter_info, item_info,
                                target_folder, create_item)
        self.platform = app.config.get(prefs.APP_PLATFORM)

    def get_executable(self):
        return utils.get_ffmpeg2theora_executable_path()

    def get_parameters(self):
        default_parameters = build_parameters(
            self.input_path, self.temp_output_path, self.converter_info)
        return utils.customize_ffmpeg2theora_parameters(default_parameters)

    def check_for_errors(self, line):
        return

    def monitor_progress(self, line):
        if line.startswith('f2t'):
            if self.duration is None:
                match = FFMpeg2TheoraConversionTask.DURATION_RE.match(line)
                if match is not None:
                    self.duration = float(match.group(1))
            match = FFMpeg2TheoraConversionTask.PROGRESS_RE2.match(line)
            if match is not None:
                return float(match.group(1)) / self.duration
            match = FFMpeg2TheoraConversionTask.RESULT_RE2.match(line)
            if match is not None:
                return 1.0
        else:
            match = FFMpeg2TheoraConversionTask.PROGRESS_RE1.match(line)
            if match is not None:
                if self.duration is None:
                    self.duration = float(match.group(1))
                return float(match.group(2)) / self.duration
            match = FFMpeg2TheoraConversionTask.RESULT_RE1.match(line)
            if match is not None:
                return 1.0
        return self.progress


def convert(converter_id, item_info):
    """Given a converter and an item, this starts the conversion for
    that item.
    """
    conversion_manager.start_conversion(converter_id, item_info)


@eventloop.as_idle
def _create_item_for_conversion(filename, source_info, conversion_name):
    """Make a new FileItem for a converted file."""

    # Note: We are adding things to the database.  This function
    # should only get called in the event loop.

    name = _('%(original_name)s (Converted to %(format)s)',
            {'original_name': source_info.name, 'format': conversion_name})

    fp_values = item.fp_values_for_file(filename, name,
            source_info.description)
    manual_feed = models.Feed.get_manual_feed()
    models.FileItem(filename, feed_id=manual_feed.id,
                    fp_values=fp_values)

# FIXME - this should be in an init() and not module-level
utils.setup_ffmpeg_presets()
conversion_manager = ConversionManager()
