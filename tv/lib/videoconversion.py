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
import re
import time
import Queue
import logging
import threading
import subprocess

from glob import glob
from ConfigParser import SafeConfigParser

from miro import prefs
from miro import config
from miro import signals
from miro import messages
from miro.plat import utils
from miro.plat import resources


class VideoConversionManager(signals.SignalEmitter):

    def __init__(self):
        signals.SignalEmitter.__init__(self, 'thread-will-start',
                                             'thread-started',
                                             'thread-did-start',
                                             'begin-loop',
                                             'end-loop')
        self.converters = list()
        self.task_loop = None
        self.pending_messages = Queue.Queue(-1)
        self.pending_tasks = Queue.Queue(-1)
        self.running_tasks = dict()
        self.quit_flag = False
        self.max_concurrent_tasks = utils.get_logical_cpu_count()
    
    def load_converters(self):
        groups = glob(resources.path('conversions/*.conv'))
        for group_definition in groups:
            parser = SafeConfigParser()
            definition_file = open(group_definition)
            try:
                parser.readfp(definition_file)
                defaults = parser.defaults()
                sections = parser.sections()
                group_converters = list()
                for section in sections:
                    converter_info = VideoConverterInfo(section, parser, defaults)
                    group_converters.append(converter_info)
                self.converters.append((defaults['name'], group_converters))
            finally:
                definition_file.close()
    
    def shutdown(self):
        if self.task_loop is not None:
            self.interrupt_all()
            self.task_loop.join()

    def interrupt_all(self):
        self.pending_messages.put("interrupt_all")
    
    def get_converters(self):
        return self.converters
    
    def start_conversion(self, converter_info, item_info, target_folder=None):
        task = self._make_conversion_task(converter_info, item_info, target_folder)
        if task is not None and task.get_executable() is not None:
            self._check_task_loop()
            self.pending_tasks.put(task)
    
    def get_default_target_folder(self):
        root = config.get(prefs.MOVIES_DIRECTORY)
        target_folder = os.path.join(root, "Converted")
        if not os.path.exists(target_folder):
            os.mkdir(target_folder)
        return target_folder
        
    def _make_conversion_task(self, converter_info, item_info, target_folder):
        if target_folder is None:
            target_folder = self.get_default_target_folder()
        if converter_info.executable == 'ffmpeg':
            return FFMpegConversionTask(converter_info, item_info, target_folder)
        elif converter_info.executable == 'ffmpeg2theora':
            return FFMpeg2TheoraConversionTask(converter_info, item_info, target_folder)
        return None
    
    def _check_task_loop(self):
        if self.task_loop is None:
            self.task_loop = threading.Thread(target=self._loop, name="Conversion Loop")
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
        logging.debug("Conversions manager thread loop finished.")
    
    def _run_loop_cycle(self):
        try:
            msg = self.pending_messages.get_nowait()
            if msg == 'interrupt_all':
                self._terminate()
                return
        except Queue.Empty, e:
            pass

        notify = False
        if len(self.running_tasks) < self.max_concurrent_tasks:
            try:
                task = self.pending_tasks.get_nowait()
                if not task.key in self.running_tasks:
                    self.running_tasks[task.key] = task
                    task.run()
                    notify = True
            except Queue.Empty, e:
                pass

        for key in self.running_tasks.keys():
            task = self.running_tasks[key]
            if task.is_finished():
                self.running_tasks.pop(key)
                notify = True
        
        if notify:
            self._notify_running_tasks()
            
        time.sleep(0.2)
    
    def _notify_running_tasks(self):
        count = len(self.running_tasks)
        message = messages.VideoConversionsCountChanged(count)
        message.send_to_frontend()
    
    def _terminate(self):
        if self.pending_tasks.qsize() > 0:
            logging.debug("Clearing pending conversion tasks...")
            while not self.pending_tasks.empty():
                self.pending_tasks.get()
        if len(self.running_tasks) > 0:
            logging.debug("Interrupting running conversion tasks...")
            for task in self.running_tasks.itervalues():
                task.interrupt()
        self.quit_flag = True
    

class VideoConversionTask(object):

    def __init__(self, converter_info, item_info, target_folder):
        self.converter_info = converter_info
        self.input_path = item_info.video_path
        self.output_path = self._build_output_path(self.input_path, target_folder)
        self.key = "%s->%s" % (self.input_path, self.output_path)
        self.thread = None
        self.duration = None
        self.progress = 0
    
    def get_executable(self):
        raise NotImplementedError()
    
    def get_parameters(self):
        def substitute(param):
            if param == "{input}":
                return self.input_path
            elif param == "{output}":
                return self.output_path
            elif param == "{ssize}":
                return self.converter_info.screen_size
            return param
        return map(substitute, self.converter_info.parameters.split())
            
    def _build_output_path(self, input_path, target_folder):
        basename = os.path.basename(input_path)
        basename, _ = os.path.splitext(basename)
        target_name = "%s.%s" % (basename, self.converter_info.extension)
        return os.path.join(target_folder, target_name)

    def run(self):
        self.thread = threading.Thread(target=self._loop, name="Conversion Task")
        self.thread.setDaemon(True)
        self.thread.start()
        
    def is_finished(self):
        return self.thread is not None and not self.thread.isAlive()

    def _loop(self):
        executable = self.get_executable()
        args = self.get_parameters()
        self.process_handle = subprocess.Popen(args, executable=executable, 
                                                     bufsize=1, 
                                                     stdout=subprocess.PIPE,
                                                     stderr=subprocess.PIPE, 
                                                     close_fds=True)
        keep_going = True
        while keep_going:
            line = self.readline()
            if line == "":
                keep_going = False
            else:
                self.progress = self.monitor_progress(line.strip())
                if self.progress > 1.0:
                    self.progress = 1.0

    def interrupt(self):
        utils.kill_process(self.process_handle.pid)
        if os.path.exists(self.output_path) and self.progress < 1.0:
            os.remove(self.output_path)


class FFMpegConversionTask(VideoConversionTask):
    DURATION_RE = re.compile('Duration: (\d\d):(\d\d):(\d\d)\.(\d\d), start:.*, bitrate:.*')
    PROGRESS_RE = re.compile('frame=.* fps=.* q=.* L?size=.* time=(.*) bitrate=(.*) dup=.* drop=.*')

    def get_executable(self):
        return utils.get_ffmpeg_executable_path()

    def get_parameters(self):
        parameters = VideoConversionTask.get_parameters(self)
        parameters.insert(0, "-y")
        return parameters

    def readline(self):
        return self.process_handle.stderr.readline()

    def monitor_progress(self, line):
        if self.duration is None:
            match = self.DURATION_RE.match(line)
            if match is not None:
                hours = match.group(1)
                minutes = match.group(2)
                seconds = match.group(3)
                frames = match.group(4)
                self.duration = int(hours) * 60 * 60 + int(minutes) * 60 + int(seconds)
        else:
            match = self.PROGRESS_RE.match(line)
            if match is not None:
                return float(match.group(1)) / self.duration
        return self.progress
    

class FFMpeg2TheoraConversionTask(VideoConversionTask):
    PROGRESS_RE = re.compile('\{"duration":(.*), "position":(.*), "audio_kbps":.*, "video_kbps":.*, "remaining":.*\}')
    RESULT_RE = re.compile('\{"result": "(.*)"\}')

    def get_executable(self):
        return utils.get_ffmpeg2theora_executable_path()

    def readline(self):
        return self.process_handle.stdout.readline()

    def monitor_progress(self, line):
        match = self.PROGRESS_RE.match(line)
        if match is not None:
            if self.duration is None:
                self.duration = float(match.group(1))
            return float(match.group(2)) / self.duration
        return self.progress



class VideoConverterInfo(object):

    def __init__(self, name, config, defaults):
        self.name = name
        self.executable = self._get_config_value(name, config, defaults, "executable")
        self.parameters = self._get_config_value(name, config, defaults, "parameters")
        self.extension = self._get_config_value(name, config, defaults, "extension")
        self.screen_size = self._get_config_value(name, config, defaults, "ssize")

    def _get_config_value(self, section, config, defaults, key):
        try:
            return config.get(section, key)
        except:
            return defaults.get(key)


class VideoConversionCommand(object):
    def __init__(self, item_info, converter):
        self.item_info = item_info
        self.converter = converter
    def launch(self):
        conversion_manager.start_conversion(self.converter, self.item_info)


conversion_manager = VideoConversionManager()
