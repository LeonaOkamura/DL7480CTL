# -*- coding: utf-8 -*-

""" Yokogawa DL74x0 oscilloscope controller
*
* This program provides GUI to control DL74x0 oscilloscope
* [Prerequisite]
*  - YKDL1700.8 installed
*  - NI-VISA installed
*
* to compile:
* % $env:http_proxy="http://127.0.0.1:9000"
* % $env:https_proxy="http://127.0.0.1:9000"
* % pipenv --python 3.11
* % pipenv shell
* % pyinstaller .\DL7480CTL.py --onefile --noconsole
*  
* [note] Semantec gives a fault positive on a exe file made by nuitka. 
"""

import pyvisa
import tkinter as tk
import tkinter.simpledialog as simpledialog
import win32clipboard as clip  # pip install pywin32
import win32con
from io import BytesIO
from PIL import Image
from plyer import notification
import pystray
import tempfile
import io
import os
import shutil
import re
from win32api import GetMonitorInfo, MonitorFromPoint
import time


def send_img_to_clipboard(imgfile, imgRatio):
    """copy a image file into Windows clipboard

    Args:
        imgfile : file name to load  
    """
    output = BytesIO()
    with Image.open(imgfile) as img:
        ww = int(img.width * imgRatio)
        hh = int(img.height * imgRatio)
        img.resize((ww, hh)).convert('RGB').save(output, 'BMP')
    data = output.getvalue()[14:]
    #image.close()
    output.close()

    clip.OpenClipboard()
    clip.EmptyClipboard()
    clip.SetClipboardData(win32con.CF_DIB, data)
    clip.CloseClipboard()


class Gui:
    '''provides GUI contoller for Yokogawa DL74x0 
    
        +----------------------------------------+---+
        | DL74x0 controller                      | x |
        +----------------------------------------+---+
        |             [capture]                 ⬤    |
        | save:  [1] [2] [3] [4] [5] [6] [7] [8]     |
        | load:  [1] [2] [3] [4] [5] [6] [7] [8]     |
        |                                     [cog]  |
        +--------------------------------------------+
    '''
    FILENAME_PREFIX = 'DL74x0-'
    SYSTRAY_TITLE = 'DL74x0'

    def __init__(self, root):
        self.dl7480 = YokogawaDL7480()
        self.status = 'init'
        self.lastSavedId = -1   # not saved
        self.imgRatio = 1.0

        frameT = tk.Frame(root)
        frameM = tk.Frame(root)
        frameB = tk.Frame(root)
        frameBB = tk.Frame(root, height=16)
        frameT.pack(fill=tk.X, expand=True)
        frameM.pack(fill=tk.X, expand=True)
        frameB.pack(fill=tk.X, expand=True)
        frameBB.pack(fill=tk.X, expand=True)

        self.lblStatus = tk.Label(frameT, text='⬤', fg='black')
        self.lblStatus.pack(side=tk.RIGHT, padx=10)
        tk.Button(frameT, text='capture', command=lambda:self.capture()).pack(side=tk.LEFT, expand=True, ipadx=10)

        tk.Label(frameM, text='save').pack(side=tk.LEFT)
        tk.Button(frameM, text='1', command=lambda:self.saveconfig(1)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameM, text='2', command=lambda:self.saveconfig(2)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameM, text='3', command=lambda:self.saveconfig(3)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameM, text='4', command=lambda:self.saveconfig(4)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameM, text='5', command=lambda:self.saveconfig(5)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameM, text='6', command=lambda:self.saveconfig(6)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameM, text='7', command=lambda:self.saveconfig(7)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameM, text='8', command=lambda:self.saveconfig(8)).pack(side=tk.LEFT, padx=2)
        self.btnUndoSave = tk.Button(frameM, text='undo')
        self.btnUndoSave.pack(padx=4)
        self.updateBtnUndoSave('disabled')

        tk.Label(frameB, text='load').pack(side=tk.LEFT)
        tk.Button(frameB, text='1', command=lambda:self.loadconfig(1)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameB, text='2', command=lambda:self.loadconfig(2)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameB, text='3', command=lambda:self.loadconfig(3)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameB, text='4', command=lambda:self.loadconfig(4)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameB, text='5', command=lambda:self.loadconfig(5)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameB, text='6', command=lambda:self.loadconfig(6)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameB, text='7', command=lambda:self.loadconfig(7)).pack(side=tk.LEFT, padx=2)
        tk.Button(frameB, text='8', command=lambda:self.loadconfig(8)).pack(side=tk.LEFT, padx=2)
        self.btnUndoLoad = tk.Button(frameB, text='undo')
        self.btnUndoLoad.pack(padx=4)
        self.updateBtnUndoLoad('disabled')

        tk.Button(frameBB, width=24, height=24, image=COG_IMG, command=self.dialogImgRatio).pack(side=tk.RIGHT, padx=2)
    

    def dialogImgRatio(self):
        '''show diaglog to update self.imgRatio (0.1 to 2.0)
        '''
        r = simpledialog.askfloat('Screenshot ratio', 'Screenshot ratio (0.1 to 2.0)', initialvalue=self.imgRatio, minvalue=0.1, maxvalue=2.0)
        if r != None:
            r = min(2.0, max(0.1, r))
        self.imgRatio = r


    def updateBtnUndoSave(self, state):
        self.btnUndoSave['state'] = state


    def updateBtnUndoLoad(self, state):
        self.btnUndoLoad['state'] = state

    
    def undoSave(self):
        '''undo last save = rename bkup.dat to `lastsaveID`.dat 
        '''
        if self.lastSavedId > 0:
            datfile  = '{}\\{}{}.dat'.format(os.getcwd(), self.FILENAME_PREFIX, self.lastSavedId)
            bkupfile = '{}\\{}bkup.dat'.format(os.getcwd(), self.FILENAME_PREFIX)
            if os.path.exists(bkupfile):
                shutil.move(bkupfile, datfile)
            self.lastSavedID = -1
            self.updateBtnUndoSave('disabled')


    def undoLoad(self, arg):
        '''unload last load = revert the configuration back by applying bkup.dat
        '''
        datfile  = '{}\\{}{}.dat'.format(os.getcwd(), self.FILENAME_PREFIX, arg)
        bkupfile = '{}\\{}bkup.dat'.format(os.getcwd(), self.FILENAME_PREFIX)
        if os.path.exists(bkupfile):
            with open(bkupfile, 'r') as fp:
                for line in fp:
                    self.dl7480.setconfig(line)
            shutil.remove(bkupfile)
            self.updateBtnUndoLoad('disabled')

        else:
            notification.notify(title=self.SYSTRAY_TITLE, message=f'{bkupfile} not found.', timeout=5)


    def saveconfig(self, arg):
        '''acquire the configurations from the oscilloscope and save it into a file

        Args:
            arg (int): specifies the data file number to save
        Returns:
            0  : failed to save the data
            >0 : data file number 
        '''
        self.changeCursor('wait')

        if self.dl7480.connect() == False:
            self.setStatus('failed')
            self.changeCursor('')
            return(0)
        else:
            self.setStatus('connected')

        if self.getStatus() == 'connected':
            self.setStatus('connected')
            stat, lrn = self.dl7480.getconfig()  # -> ':ACQUIRE:RLENGTH 10000;MODE NORMAL; ...'
            if lrn == '':
                notification.notify(title=self.SYSTRAY_TITLE, message='no response for "*LRN" command. Aborted.', timeout=5)
                self.changeCursor('')
                return(0)
            else:
                datfile  = '{}\\{}{}.dat'.format(os.getcwd(), self.FILENAME_PREFIX, arg)
                bkupfile = '{}\\{}bkup.dat'.format(os.getcwd(), self.FILENAME_PREFIX)

                if os.path.exists(datfile):
                    shutil.copy(datfile, bkupfile)

                with open(datfile, mode='w') as fp:
                    fp.write(lrn)
                self.saveid = arg
                self.updateBtnUndoSave('active')

                notification.notify(title=self.SYSTRAY_TITLE, message='saved.', timeout=5)
                self.changeCursor('')
                return(arg)


    def loadconfig(self, arg):
        '''load the configurations and apply to the oscilloscope

        Args:
            arg (int): specifies the data file number to save
        Returns:
            0  : failed to save the data
            >0 : data file number 
        '''
        self.changeCursor('wait')
        if self.dl7480.connect() == False:
            self.setStatus('failed')
            self.changeCursor('')
            return(0)
        else:
            self.setStatus('connected')

        if self.getStatus() == 'connected':
            self.setStatus('connected')
            timeout = self.dl7480.inst.timeout
            self.dl7480.inst.timeout = 10000

            stat, lrn = self.dl7480.getconfig()  # -> ':ACQUIRE:RLENGTH 10000;MODE NORMAL; ...'
            if stat == False:
                notification.notify(title=self.SYSTRAY_TITLE, message='no response from the oscilloscope. Aborted.', timeout=5)
                self.changeCursor('')
                return(0)            
            else:
                datfile = '{}\\{}{}.dat'.format(os.getcwd(), self.FILENAME_PREFIX, arg)
                bkupfile = '{}\\{}bkup.dat'.format(os.getcwd(), self.FILENAME_PREFIX)
                with open(bkupfile, mode='w') as fp:
                    fp.write(lrn)

                if os.path.exists(datfile):
                    with open(datfile, 'r') as fp:
                        for line in fp:
                            #self.dl7480.setconfig('*WAI')
                            self.dl7480.setconfig(line)
                    self.lastSavedID = -1                
                    self.updateBtnUndoLoad('active')
                    notification.notify(title=self.SYSTRAY_TITLE, message='loaded.', timeout=5)
                    self.changeCursor('')

                    self.dl7480.inst.timeout = timeout
                    return(arg)

                else:
                    notification.notify(title=self.SYSTRAY_TITLE, message=f'{datfile} not found.', timeout=5)
                    self.changeCursor('')
                    self.dl7480.inst.timeout = timeout
                    return(0)
                    
    def capture(self):
        '''acquire a jpg file from inst.capture(), and copy it into clipboard

        Returns:
            False : failed
            True  : succeeded
        '''
        self.changeCursor('wait')

        if self.getStatus() != 'connected':
            if self.dl7480.connect() == False:
                self.setStatus('failed')
                self.changeCursor('')
                return(False)
            else:
                self.setStatus('connected')

        if self.getStatus() == 'connected':
            self.changeCursor('wait')
            captstat, captmsg = self.dl7480.capture()
            if captstat:
                # copy into clipboard and them remove the tmpfile
                send_img_to_clipboard(captmsg, self.imgRatio)
                self.changeCursor('')
                notification.notify(title=self.SYSTRAY_TITLE, message=f'screenshot is in your clipboard.', timeout=5)

                try:
                    os.remove(captmsg)
                    return(True)
                except:
                    return(False)
    
            else:
                notification.notify(title=self.SYSTRAY_TITLE, message=captmsg, timeout=5)
                self.changeCursor('')
                return(False)
                

    def setStatus(self, arg):
        match(arg):
            case 'init':
                self.status = 'init'
                self.lblStatus.config(fg='grey')
            case 'connected':
                self.status = 'connected'
                self.lblStatus.config(fg='green')
            case _:
                self.status = 'failed'
                self.lblStatus.config(fg='red')

    def getStatus(self):
        match self.status:
            case 'init':
                return('init')
            case 'connected':
                return('connected')
            case _:
                self.status = 'failed'
                return('failed')

    def changeCursor(self, type):
        root.config(cursor=type)
        root.update()


class YokogawaDL7480(BaseException):
    '''A class to control Yokogawa DL74x0 oscilloscope
    '''
    # constructor
    def __init__(self):
        self.rm = None
        self.inst = None
        self.devname = ''
        self.opt = ''

    # destructor
    def __del__(self):
        if self.inst != None:
            self.inst.before_close()
            self.inst.close()
            self.inst = None
            self.devname = ''
            self.opt = ''

        if self.rm != None:
            self.rm.close()
            self.rm = None

    def connect(self):
        '''set 'inst' to connect to DL74x0 oscilloscope

        Returns:
            True : connection succeeded
            False: connection failed 
        '''
        if self.inst != None:
            return(True)    # connected

        self.rm = pyvisa.ResourceManager()
        visa_list = self.rm.list_resources('USB?*') # default value '?*::INSTR' doesn't match 'USB0::0x0B21::0x0001::NI-VISA-30001::RAW'
        for src in visa_list:
            if self.inst == None:
                print(f'connecting to {src}')
                dev = self.rm.open_resource(src)
                dev.write_termination = '\n'
                dev.read_termination = '\n'
                try:
                    idn = dev.query('*IDN?;')
                    print(idn)
                except:   
                    # VI_ERROR_TMO (-1073807339): Timeout expired before operation completed.
                    print('query() timed out.')
                else:
                    if re.match(r'YOKOGAWA,7014[56]0', idn):  # 701450 : DL7440 4MW memory, 701460 : DL7440 16MW memory
                        self.devname = 'DL7440'
                        self.inst = dev
                        self.inst.delay = 100    # 100 ms delay after every write
                        self.inst.timeout = 5000   # 5 seconds for timeout
                        self.inst.term_char = '\n'
                        self.opt = self.inst.query('*OPT?;').strip() # -> 'CH4MW,FLOPPY,PRINTER,LOGIC,SCSI,ETHER,USERDEFINE
                        print(f'connect(): connected to {src}')
                        break

                    if re.match(r'YOKOGAWA,7014[78]0', idn):  # 701470 : DL7480 4MW memory, 701480 : DL7480 16MW memory
                        self.devname = 'DL7480'
                        self.inst = dev
                        self.inst.delay = 100    # 100 ms delay after every write
                        self.inst.timeout = 5000   # 5 seconds for timeout
                        self.inst.term_char = '\n'
                        self.opt = self.inst.query('*OPT?;').strip() # -> 'CH4MW,FLOPPY,PRINTER,LOGIC,SCSI,ETHER,USERDEFINE
                        print(f'connect(): connected to {src}')
                        break

        if self.inst == None:
            print('connect(): connection failed')
            #notification.notify(title=self.SYSTRAY_TITLE, message='DL74x0 not found. Aborted.', timeout=5)
            return(False)
        else:
            return(True)


    def getopt(self, arg):
        '''checks if the specified arg is available with the scope
        Usage:
            getopt('LOGIC') -> # False
            getopt('USERDEFINE') -> # False
        '''
        if self.inst == None:
            return(False)
        else:
            if(arg.upper() in self.opt.upper()):
                return(True)
            else:
                return(False)

    def capture(self):
        '''grab screenshot from DL74x0, save it into a tmpfile, and returns the name of the tmpfile 

        Returns: tuple (status, msg)
            status: true if captured as expected
            msg: filename of the screenshort or the error message
        '''
        if self.connect() == False:
            return(False, 'Oscilloscope not found')
        else:
            # inst.read_termination = '\n'
            # inst.write_termination = '\n'
            # inst.chunk_size = 102400
            self.inst.write('*CLS;;')
            self.inst.write(':IMAGe:FORMat JPEG;')
            self.inst.write(':IMAGe:TONE COLor;')
            self.inst.write(':STOP;*WAI;')

            self.inst.timeout = 10000   # 10 seconds for timeout
            self.inst.write(':IMAGe:SEND?;')
            # wait the oscilloscope for capturing completion
    
            try:
                shash = self.inst.read_bytes(count=1, break_on_termchar=False)  # -> '#'
                print(f'hash={shash}')
                if shash != b'#':
                    shash = self.inst.read_bytes(count=1, break_on_termchar=False)  # -> '#'
                    print(f'hash={shash}')
                sdigit = self.inst.read_bytes(count=1, break_on_termchar=False) # -> '6' denoting that the following six digit is the size of data 
                sbyte = self.inst.read_bytes(count=int(sdigit), break_on_termchar=False)    # -> '218566'
                print(f'sdigit={sdigit}')
                print(f'sbyte={sbyte}')
                ndigit = int(sdigit)
                nbyte = int(sbyte)
            except ValueError:
                self.inst.write('*CLS')
                return(False, 'response from oscilloscope is unexpected. Aborted.')
            except pyvisa.errors.VisaIOError:
                self.inst.write('*CLS')
                return(False, 'response from oscilloscope is unexpected. Aborted.')

            try:
                d0 = self.inst.read_bytes(1, break_on_termchar=False) # -> '\n'
                if d0 == '\n':
                    data = self.inst.read_bytes(count=nbyte, break_on_termchar=False)     # -> b'\xFF\xD8 ... \xFF\xD9'
                else:
                    data = d0 + self.inst.read_bytes(count=nbyte-1, break_on_termchar=False)
                dmy = self.inst.read_bytes(count=1, break_on_termchar=False)    # -> '\n'

                print(f'{len(data)} / {nbyte} bytes read')
                #if b'\xFF\D9' != data[len(data)-2: ]: 
                #    return(False, 'unexpected end of the jpg file')
                
            except pyvisa.errors.VisaIOError:
                return(False, 'timeout during capturing')
            

            #eesr = self.inst.query('*WAI;:STATus:EESR?') # Extended Event Register
                # <0> Running, <1> Hold, <2> Awaiting trigger, <3> Calibrating, <4> Self-testing
                # <5> Printing, <6> Accessing, <7> Measuring, <8> History search, <9> Setup
                # <10> Go/NoGo, <11> Search, <12> N-single, <13> Initializing, <14> FFT

            #print(f'eesr={eesr}')
            #if (int(eesr) >> 5) & 1:                # bit 5 : Printing is still in progress
            self.inst.write('*WAI;*CLS;')
            #self.inst.write(':COMMunicate:REMote OFF')
            #self.closeinst()

            # save data into tmpfile
            fd, tmpfile = tempfile.mkstemp(text=False, suffix='.jpg')
            with open(tmpfile, 'wb') as fp:
                fp.write(data)
            
            return(True, tmpfile)
    
    def getconfig(self):
        '''returns the current configuration

        Returns: tuple(status, msg)
            status  : true of connected
            msg : response from the scope
        '''
        if self.inst == None:
            self.connect()
            if self.inst == None:
                print('setconfig(): no DL74x0 found')
                return(False, '')
        if self.inst == None:
                print('setconfig(): no DL74x0 found')
                return(False, '')
        else:
            #lrn = self.inst.query('*LRN?')
            acqu = '*WAI;' + self.inst.query(':ACQuire?').strip() + ';\n'

            chan = ''
            chan = chan + '*WAI;' + self.inst.query(':CHANnel1?').strip() + ';\n'
            chan = chan + '*WAI;' + self.inst.query(':CHANnel2?').strip() + ';\n'
            chan = chan + '*WAI;' + self.inst.query(':CHANnel3?').strip() + ';\n'
            chan = chan + '*WAI;' + self.inst.query(':CHANnel4?').strip() + ';\n'

            if self.devname == 'DL7480':
                chan = chan + '*WAI;' + self.inst.query(':CHANnel5?').strip() + ';\n'
                chan = chan + '*WAI;' + self.inst.query(':CHANnel6?').strip() + ';\n'
                chan = chan + '*WAI;' + self.inst.query(':CHANnel7?').strip() + ';\n'
                chan = chan + '*WAI;' + self.inst.query(':CHANnel8?').strip() + ';\n'

            curs = self.splitInst(self.inst.query(':CURSor?'))

            disp = self.inst.query(':DISPlay?')
            if self.getopt('LOGIC') == False:
                #An error occurs if PODA or PODB is specified when the logic input (option) is not installed.
                disp = re.sub(r':DISPLAY:RGB:WAVEFORM:POD.+?;[:\n]', ':', disp).strip(':')
            disp = self.splitInst(disp)

            math = self.inst.query(':MATH?')
            #An error occurs if PODA or PODB is specified when the logic input (option) is not installed.
            if self.getopt('USERDEFINE') == False:
                math = re.sub(r':MATH\d:USERDEFINE:.+?;[:\n]', ':', math).strip(':')
            math = self.splitInst(math)

            meas = self.inst.query(':MEASure?')
            meas = self.splitInst(meas)

            sear = '*WAI;' + self.inst.query(':SEARch?')
            if self.getopt('LOGIC') == False:
                #An error occurs if PODA or PODB is specified when the logic input (option) is not installed.
                sear = re.sub(r':SEARCH:PPATTERN:LOGIC:.+?;[:\n]', ':', sear)
                sear = re.sub(r':SEARCH:SPATTERN:BIT:.+?;[:\n]', ':', sear)
                sear = re.sub(r':SEARCH:SPI:ANALYZE:SETUP:CS:LOGIC:.+?;[:\n]', ':', sear).strip(':')
            sear = self.splitInst(sear)

            phas = self.splitInst(self.inst.query(':PHASe?'))
            tbas = self.splitInst(self.inst.query(':TIMebase?'))
            trig = self.splitInst(self.inst.query(':TRIGger?'))
            # :TRIG:CAN: causes an error
            trig = re.sub(r':TRIG:CAN:.+?;[:\n]', ';', trig)

            zoom = '*WAI;' + self.inst.query(':ZOOM?') 
            if self.getopt('LOGIC') == False:
                #An error occurs if PODA or PODB is specified when the logic input (option) is not installed.
                zoom = re.sub(r':ZOOM:ALLOCATION:POD.+?;[:\n]', ':', zoom).strip(':')
            zoom = self.splitInst(zoom)

            #self.inst.write(':COMMunicate:REMote OFF')

            #self.closeinst()
            return(True, f':STOP;\n{acqu};\n{chan};\n{curs};\n{disp};\n{math};\n{meas};\n{sear};\n{phas};\n{tbas};\n{trig}\n{zoom};\n')


    def splitInst(self, arg):
        '''split the commands up to 1024 bytes to avoid deadlock
        '''
        if len(arg) < 1024-6:
            return('*WAI;' + arg.strip(';\n') + '\n')
        else:
            r = []
            s = ';' + arg.strip(';\n') + ';'
            m = re.search(r'^;(:.{,1018};):', s)
            while m!=None:
                r.append('*WAI;' + m.group(1) + '\n')
                s = ';:' + s[m.span(0)[1] : ]
                m = re.search(r'^;(:.{,1018};):', s)
            if len(s) > 0:
                r.append('*WAI;' + s.strip(';') + '\n')
        return(''.join(r))


    def closeinst(self):
        if self.inst != None:
            self.inst.before_close()
            self.inst.close()
            self.inst = None

        if self.rm != None:
            self.rm.close()
            self.rm = None


    def setconfig(self, arg):
        '''send the string to the oscilloscope

        Arguments:
            arg : string to send to the oscilloscope
        '''
        if self.inst == None:
            self.connect()
            if self.inst == None:
                print('setconfig(): no DL74x0 found')
                return(False)
        if self.inst == None:
                print('setconfig(): no DL74x0 found')
                return(False)
        else:
            print(arg)
            timeout = self.inst.timeout
            self.inst.timeout = 20000
            try:
                b = self.inst.write(arg)
                print(f'{b}  ' + str(len(arg)) + '\n')
                self.inst.timeout = timeout
                #self.closeinst()
                return(True)
            except pyvisa.errors.VisaIOError:
                print('setconfig(): timed out')
                self.inst.write('*CLS')
                self.inst.timeout = timeout
                #self.closeinst()
                return(False)
            #self.inst.write(':COMMunicate:REMote OFF')



if __name__=="__main__":
    root = tk.Tk()
    monitor_info = GetMonitorInfo(MonitorFromPoint((0,0)))
    monitor_area = monitor_info.get("Monitor")  # -> (0, 0, 1920, 1080)
    work_area = monitor_info.get("Work")    # -> (0, 0, 1920, 1050)

    # base64-coded icon data
    COG_B64 = '''R0lGODlhGAAYAIABAAAAAP///yH5BAEKAAEALAAAAAAYABgAAAJEjI+ggO292Hsy
    RHWqW+ZKvnliBI0mlpwipZKs212hXNLj1MJ1jufobPMAQSmd8MUbJjM+GrOpecZc
    xM2TGJ1Ms9pdtwAAOw=='''
    COG_IMG = tk.PhotoImage(data=COG_B64)

    w=240   # widget width
    h=140   # widget height
    x = work_area[2] - w - 10   # right bottom position
    y = work_area[3] - h - 30   # right bottom position

    root.geometry(f"{w}x{h}+{x}+{y}")   # position the widget at the right bottom corner
    root.title("DL74x0 controller")
    root.resizable(False, False)

    ins = Gui(root) 
    root.attributes('-toolwindow',1)    # simple title bar (works with MS-Windows only)
    root.attributes('-topmost', True)   # always on top
    root.update()
    root.mainloop()
