
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Control Audacity via mod-script-pipe and play video using VLC Media Player
Pipe Client may be used as a command-line script to send commands to
Audacity via the mod-script-pipe interface, or loaded as a module.
Requires Python 2.7 or later. Python 3 strongly recommended.
======================
Command Line Interface
======================
    usage: play_and_record.py [-h] [-t] [-f ]
    Arguments
---------
    -h,--help: optional
        show short help and exit
    -t, --timeout: float, optional
        timeout for reply in seconds (default: 10)
    -f, --file: optional
        local file or web url, such as C:/Users/Angi/Videos/my_video.mp4, or https://youtu.be/uPHt0Hw8z3I?t=6

Example
-------
    $ python3 play_and_record.py -f https://youtu.be/uPHt0Hw8z3I?t=6

============
Module Usage
============
Note that on a critical error (such as broken pipe), the module just exits.
If a more graceful shutdown is required, replace the sys.exit()'s with
exceptions.
Example
-------
    # Import the module:
    >>> import pipeclient
    # Create a client instance:
    >>> client = pipeclient.PipeClient()
    # Send a command:
    >>> client.write("Command", timer=True)
    # Read the last reply:
    >>> print(client.read())
See Also
--------
PipeClient.write : Write a command to _write_pipe.
PipeClient.read : Read Audacity's reply from pipe.
Copyright Steve Daulton 2018
Released under terms of the GNU General Public License version 2:
<http://www.gnu.org/licenses/old-licenses/gpl-2.0.html />
Modified by Angi Ye: 2020
Dependencies: psutil, tkinter
If you don't have these libraries installed, run the following
python -m pip install --upgrade pip
pip install psutil
pip install tkinter
"""

import os
import sys
import threading
import time
import errno
import argparse
import subprocess
import psutil
from tkinter import *
from tkinter import filedialog

window = Tk()

window.title('Play Video & Record Audio')

window.geometry('500x70')
filepathlbl = Label(window, text='vidoe file: mp4 or url')
filepathtxt = Entry(window, width=60)

if sys.version_info[0] < 3 and sys.version_info[1] < 7:
    sys.exit('PipeClient Error: Python 2.7 or later required')

# Platform specific constants
if sys.platform == 'win32':
    WRITE_NAME = '\\\\.\\pipe\\ToSrvPipe'
    READ_NAME = '\\\\.\\pipe\\FromSrvPipe'
    EOL = '\r\n\0'
else:
    # Linux or Mac
    PIPE_BASE = '/tmp/audacity_script_pipe.'
    WRITE_NAME = PIPE_BASE + 'to.' + str(os.getuid())
    READ_NAME = PIPE_BASE + 'from.' + str(os.getuid())
    EOL = '\n'


class PipeClient():
    """Write / read client access to Audacity via named pipes.
    Normally there should be just one instance of this class. If
    more instances are created, they all share the same state.
    __init__ calls _write_thread_start() and _read_thread_start() on
    first instantiation.
    Parameters
    ----------
        None
    Attributes
    ----------
        reader_pipe_broken : event object
            Set if pipe reader fails. Audacity may have crashed
        reply_ready : event object
            flag cleared when command sent and set when response received
        timer : bool
            When true, time the command execution (default False)
        reply : string
            message received when Audacity completes the command
    See Also
    --------
    write : Write a command to _write_pipe.
    read : Read Audacity's reply from pipe.
    """

    reader_pipe_broken = threading.Event()
    reply_ready = threading.Event()

    _shared_state = {}

    def __new__(cls, *p, **k):
        self = object.__new__(cls, *p, **k)
        self.__dict__ = cls._shared_state
        return self

    def __init__(self):
        self.check_and_launch_audacity()
        self.timer = False
        self._start_time = 0
        self._write_pipe = None
        self.reply = ''
        if not self._write_pipe:
            self._write_thread_start()
        self._read_thread_start()

    def check_and_launch_audacity(self):
        audacity_name = "audacity.exe"
        process = filter(lambda p: p.name() == audacity_name, psutil.process_iter())
        audacity_running = False
        for p in psutil.process_iter():
            if p.name() == audacity_name:
                print (p)
                audacity_running = True

        if not audacity_running:
            audacicy = os.getenv('PROGRAMFILES(X86)','C:\\Program Files (x86)') + '/Audacity/' + audacity_name
            proc = subprocess.Popen([audacicy], stdout=subprocess.PIPE, shell=False)
            if proc:
                print('Started Audacity with PID = ', proc.pid)
                time.sleep(2)

    def _write_thread_start(self):
        """Start _write_pipe thread"""
        # Pipe is opened in a new thread so that we don't
        # freeze if Audacity is not running.
        write_thread = threading.Thread(target=self._write_pipe_open)
        write_thread.daemon = True
        write_thread.start()
        # Allow a little time for connection to be made.
        time.sleep(0.1)
        if not self._write_pipe:
            sys.exit('PipeClientError: Write pipe cannot be opened.')

    def _write_pipe_open(self):
        """Open _write_pipe."""
        self._write_pipe = open(WRITE_NAME, 'w')

    def _read_thread_start(self):
        """Start read_pipe thread."""
        read_thread = threading.Thread(target=self._reader)
        read_thread.daemon = True
        read_thread.start()

    def write(self, command, timer=False):
        """Write a command to _write_pipe.
        Parameters
        ----------
            command : string
                The command to send to Audacity
            timer : bool, optional
                If true, time the execution of the command
        Example
        -------
            write("GetInfo: Type=Labels", timer=True):
        """
        self.timer = timer
        print('Sending command:', command)
        self._write_pipe.write(command + EOL)
        # Check that read pipe is alive
        if PipeClient.reader_pipe_broken.isSet():
            sys.exit('PipeClient: Read-pipe error.')
        try:
            self._write_pipe.flush()
            if self.timer:
                self._start_time = time.time()
            self.reply = ''
            PipeClient.reply_ready.clear()
        except IOError as err:
            if err.errno == errno.EPIPE:
                sys.exit('PipeClient: Write-pipe error.')
            else:
                raise

    def _reader(self):
        """Read FIFO in worker thread."""
        # Thread will wait at this read until it connects.
        # Connection should occur as soon as _write_pipe has connected.
        read_pipe = open(READ_NAME, 'r')
        message = ''
        pipe_ok = True
        while pipe_ok:
            line = read_pipe.readline()
            # Stop timer as soon as we get first line of response.
            stop_time = time.time()
            while pipe_ok and line != '\n':
                message += line
                line = read_pipe.readline()
                if line == '':
                    # No data in read_pipe indicates that the pipe is broken
                    # (Audacity may have crashed).
                    PipeClient.reader_pipe_broken.set()
                    pipe_ok = False
            if self.timer:
                xtime = (stop_time - self._start_time) * 1000
                message += 'Execution time: {0:.2f}ms'.format(xtime)
            self.reply = message
            PipeClient.reply_ready.set()
            message = ''
        read_pipe.close()

    def read(self):
        """Read Audacity's reply from pipe.
        Returns
        -------
        string
            The reply from the last command sent to Audacity, or null string
            if reply not received. Null string usually indicates that Audacity
            is still processing the last command.
        """
        if not PipeClient.reply_ready.isSet():
            return ''
        return self.reply


def bool_from_string(strval):
    """Return boolean value from string"""
    if strval.lower() in ('true', 't', '1', 'yes', 'y'):
        return True
    if strval.lower() in ('false', 'f', '0', 'no', 'n'):
        return False
    raise argparse.ArgumentTypeError('Boolean value expected.')

def send_message_to_audacity(client, message, timeout):
    reply = ''
    client.write(message, timer=True)
    start = time.time()
    while reply == '':
        time.sleep(0.1)  # allow time for reply
        if time.time() - start > timeout:
            reply = 'PipeClient: Reply timed-out.'
        else:
            reply = client.read()
    print(reply)



vlc_player = os.getenv('PROGRAMFILES','C:\\Program Files') + '/VideoLAN/VLC/vlc.exe'
client = PipeClient()
timeout = 10

def do_work():
        send_message_to_audacity(client, 'Record2ndChoice', timeout)
        subprocess.call([vlc_player, filepathtxt.get(), '--width', '1080', '--height', '960'])
        send_message_to_audacity(client, 'PlayStop', timeout)

def abc():
    """Start Audacity recording and VLC playing"""

    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--timeout', type=float, metavar='', default=10,
                        help="timeout for reply in seconds (default: 10")
    parser.add_argument('-f', '--file', default='https://youtu.be/uPHt0Hw8z3I?t=6')
    args = parser.parse_args()

    video_file = ''
    if (args.file):
        video_file = args.file

    client = PipeClient()
    while True:
        send_message_to_audacity(client, 'Record2ndChoice', args.timeout)

        subprocess.call([vlc_player, video_file])

        send_message_to_audacity(client, 'PlayStop', args.timeout)
        if sys.version_info[0] < 3:
            message = input("\nEnter to continue or 'Q' to quit: ")
        else:
            message = input(
                "\nEnter command or 'Q' to quit: ")
        if message.upper() == 'Q':
            sys.exit(0)

# layout
col = 0
filepathlbl.grid(column=col, row=0)
col+=1
filepathtxt.grid(column=col, row=0)
startbutton = Button(window, text='Start', command=do_work)
startbutton.grid(column=0, row=1)

window.mainloop()

#if __name__ == '__main__':
#    main()