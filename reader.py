import http.server
import socket
import datetime
import os
import matplotlib.lines
import wx
import http
import threading
from typing import Dict, List, Tuple, Any
import json
import sys
import logging
import matplotlib
matplotlib.use('Agg')
from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
import matplotlib.pyplot as plt

latestData: Dict[str, Dict[str, Any]] = {}
EVT_GOT_DATA = wx.NewIdRef()

def getIp() -> str:
    """Get local IP of current machine.

    Returns:
        str: IP address of current machine.
    """    
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(('192.168.1.1', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


def read() -> List[Dict[str, float]]:
    """Read environment data from the sensors.

    Returns:
        List[Dict[str, float]]: List of information from the sensors.
    """    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(3)  # Seconds of timeout
    sock.bind((getIp(), 0))
    sock.sendto(b'GET DATA', ('255.255.255.255', 12345))
    rawData = None
    while True:
        try:
            rawData, addr = sock.recvfrom(1024)
            print('Received from', addr, ':', rawData)
        except:
            print('Nothing more to read')
            break

    sock.close()
    if rawData is None:
        return []
    else:
        data = json.loads(rawData.decode())
        return [data]


class StreamToLoggerAndUi(object):
    """Redirect stream outputs to logger and GUI"""

    def __init__(self, logger: logging.Logger, textCtrl: wx.TextCtrl,
                 logLevel=logging.INFO):
        self.logger = logger
        self.logLevel = logLevel
        self.textCtrl = textCtrl
        self.lineBuffer = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.logLevel, line.rstrip())
            if self.textCtrl is not None and bool(self.textCtrl):
                data = {
                    'asctime': datetime.datetime.now().isoformat(),
                    'message': line.rstrip()
                    }
                msg = '%(asctime)s %(message)s\n' % data
                self.textCtrl.AppendText(msg)
    
    def setTextCtrl(self, textCtrl: wx.TextCtrl):
        if textCtrl is None:
            self.textCtrl = None
        else:
            self.textCtrl = textCtrl


class ViewerRequestHandler(http.server.BaseHTTPRequestHandler):
    """Handler for HTTP requests from LabVIEW"""
    def __init__(self, request, client_address, server) -> None:
        self.routes = [
            ('GET', '/latest', self.getLatestRecords, 'text/xml'),
            ('GET', '/test', self.getTestData, 'text/xml'),
            ('GET', '/metrics', self.getPrometheusMetrics, 'text/plain'),
            ('GET', '/version', self.getPrometheusVersion, 'application/json'),
            ('GET', '/health', self.getPrometheusHealth, 'application/json')
        ]
        super().__init__(request, client_address, server)

    def do_GET(self):
        for method, endpoint, func, contentType in self.routes:
            if method == 'GET' and self.path.startswith(endpoint):
                data = func()
                self.send_response(200)
                self.send_header('Content-Type', contentType)
                self.end_headers()
                if type(data) != str:
                    if 'xml' in contentType:
                        self.wfile.write(self.dict2xml(data).encode())
                    elif 'json' in contentType:
                        self.wfile.write(json.dumps(data).encode())
                else:
                    self.wfile.write(data.encode())
                return
        self.send_response(404, 'Not Found')
        self.end_headers()
        
    def getLatestRecords(self):
        keys = list(latestData.keys())
        keys.sort()
        return [latestData[key] for key in keys]

    def getTestData(self):
        return [{'test': 1, 'test2': '2', 'test3': '2001-01-01 12:00:02'},
                {'test': 4, 'test2': 'a', 'test3': '2021-11-01 12:00:02'}]
    
    def dict2xml(self, dics: List[Dict[str, Any]]) -> str:
        result = '<?xml version=\'1.0\' standalone=\'yes\' ?><root>'
        for dic in dics:
            result += '<reading ' 
            for key, val in dic.items():
                result += f'{key}="{val}" '
            result += '/>'
        result += '</root>'
        return result
    
    def getPrometheusHealth(self):
        """Endpoint for health indication for Prometheus.

        Returns:
            dict: health information, always "ok".
        """        
        return {'health': 'ok'}
    
    def getPrometheusVersion(self):
        """Endpoint for version information for Prometheus.

        Returns:
            dict: version information.
        """     
        return {'version': "0.1-20240901",
                "platform": sys.platform,
                "pythonVersion": sys.version}
    
    def getPrometheusMetrics(self):
        """Endpoint for metric scraping for Prometheus.

        Returns:
            str: Text data for metric values and description.
        """     
        result = ('# HELP temperature Temperature in Celsius\n'
                  '# TYPE temperature gauge\n'
                  '# HELP humidity Humidity in RH%\n'
                  '# TYPE humidity gauge\n'
                  '# HELP pressure Pressure in Pa\n'
                  '# TYPE pressure gauge\n'
                  '# HELP altitude Estimated altitude in Meter\n'
                  '# TYPE altitude gauge\n'
                  '# HELP num_sensor Number of available sensors\n'
                  '# TYPE num_sensor gauge\n')
        for device, data in latestData.items():
            for key, value in data.items():
                if key in ['device', 'time']:
                    continue
                result += f'{key}{{device="{device}"}} {value}\n'
        result += f'num_sensor {len(latestData)}'
        return result
        

class ServerThread(threading.Thread):
    """Thread for running web server in background"""
    def __init__(self):
        threading.Thread.__init__(self)
        self.server = http.server.HTTPServer(('', 12346), ViewerRequestHandler)
        self.start()
    
    def run(self):
        self.server.serve_forever()
    
    def abort(self):
        self.server.shutdown()


class GotDataEvent(wx.PyEvent):
    """Event for main window for receiving sensor readings"""
    def __init__(self, data):
        super().__init__()
        self.SetEventType(EVT_GOT_DATA)
        self.data = data


class ReaderThread(threading.Thread):
    """Run the measurement code in a separate thread to avoid freeze"""
    def __init__(self, window: wx.Frame) -> None:
        threading.Thread.__init__(self)
        self.window = window
        self.running = True
        self.start()

    def run(self):
        readings = read()
        if self.running:
            wx.PostEvent(self.window, GotDataEvent(readings))

    def abort(self):
        self.running = False


class ViewerFrame(wx.Frame):
    """Main frame of Viewer window.
    """    
    __logDir = 'logs'  # Directory of logging
    __fields = ['temperature', 'humidity']  # Fields to plot
    __numPoints = 600  # Number of points to plot
    __plots: Dict[str, Dict[str, List[matplotlib.lines.Line2D]]] = {}  # plots to display
    __colors = ['red', 'blue', 'orange', 'pink']

    def __init__(self):
        super(wx.Frame, self).__init__(None, title='Environment monitor')

        # Initialize data holder
        self.data: Dict[str, Dict[str, Tuple[List[datetime.datetime], List[float]]]] = {f: {} for f in self.__fields}
        self.__plots = {f: {} for f in self.__fields}
        
        nb = wx.Notebook(self)
        # Tab for data figure
        panel1 = wx.Panel(nb)
        self.figure = plt.figure()
        self.figure.suptitle('Lab Environment Recording')
        self.axes = [self.figure.add_subplot(len(self.__fields), 1, i + 1) 
                     for i in range(len(self.__fields))]
        self.figure.tight_layout()
        self.figurePanel = FigureCanvas(panel1, -1, self.figure)

        grid = wx.GridBagSizer(1, 3)
        grid.Add(self.figurePanel, (0, 0), (1, 1), flag=wx.EXPAND | wx.ALL)

        grid.AddGrowableCol(0, 1)
        grid.AddGrowableRow(0, 1)
        panel1.SetSizer(grid)

        # Tab for logging
        panel2 = wx.Panel(nb)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.loggerText = wx.TextCtrl(panel2, style=wx.TE_READONLY | wx.TE_MULTILINE)
        sizer.Add(self.loggerText, flag=wx.EXPAND | wx.ALL, proportion=1)
        panel2.SetSizer(sizer)

        nb.AddPage(panel1, 'Data Display')
        nb.AddPage(panel2, 'Logging')

        # Configure logger
        if isinstance(sys.stdout, StreamToLoggerAndUi):
            sys.stdout.setTextCtrl(self.loggerText)
        if isinstance(sys.stderr, StreamToLoggerAndUi):
            sys.stderr.setTextCtrl(self.loggerText)

        self.SetClientSize(panel1.GetBestSize())

        # Set timed jobs
        self.timer = wx.Timer(self, 1)
        self.Bind(wx.EVT_TIMER, self.timedLoop)
        self.timer.Start(3000)

        self.worker = ServerThread()
        self.readingWorker = ReaderThread(self)

        # Close server when window closes
        self.Bind(wx.EVT_CLOSE, self.onClose)
        # Event handler of receiving data
        self.Connect(-1, -1, EVT_GOT_DATA, self.getReadings)

        # Set Window icon
        if sys.platform == 'win32':
            dllName = os.path.join(os.getenv('SystemRoot'), 'system32', 'shell32.dll')
            icon = wx.Icon(dllName + ";12", wx.BITMAP_TYPE_ICO)
            self.SetIcon(icon)

            # Set icon for taskbar of Win7+
            import ctypes
            myappid = 'kemege.sensor.viewer' # arbitrary string
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    def updateFigure(self, forceRedraw=False):
        """Update the figures according to the data in memory.
        """
        for idx, f in enumerate(self.__fields):
            if len(self.data[f]) != len(self.__plots[f]) or forceRedraw:
                # Number of sensors changed, replot whole data
                ax = self.axes[idx]
                ax.clear()
                self.__plots[f] = {}
                for name in self.data[f]:
                    xs, ys = self.data[f][name]
                    line, = ax.plot(xs, ys, label=name, color=self.__colors[idx])
                    self.__plots[f][name] = line
                ax.set_xlabel('Time')
                ax.set_ylabel(f)
                ax.grid(True)
                ax.legend()
            else:
                # Update values of existing data
                for name in self.data[f]:
                    xs, ys = self.data[f][name]
                    self.__plots[f][name].set_data(xs, ys)
            self.axes[idx].autoscale()
            self.axes[idx].relim()
        self.figure.tight_layout()
        self.figure.autofmt_xdate()
        self.figurePanel.draw()
    
    def getLogFilename(self) -> str:
        """Get filename for logging, and create the file if it does not exist.

        Returns:
            str: Filename of log file.
        """
        if not os.path.isdir(self.__logDir):
            os.mkdir(self.__logDir)

        filename = datetime.date.today().isoformat() + '.log'
        fullName = os.path.join(self.__logDir, filename)
        if not os.path.exists(fullName):
            with open(fullName, 'w') as fp:
                fp.write('Time,Device,Temperature (C),Humidity (%RH),'
                         'Pressure (Pa),Altitude (m)\n')
        return fullName

    def getReadings(self, event=None) -> None:
        """Get readings from sensors, and store them in memory & file.
        """
        if event is None:
            readings = read()
        else:
            readings = event.data
        # Write to log file
        timeValue = datetime.datetime.now()
        timeString = timeValue.isoformat()
        dataLines = []
        for r in readings:
            dataLines.append(f'{timeString},{r["device"]},{r["temperature"]},'
                             f'{r["humidity"]},{r["pressure"]},{r["altitude"]}\n')
        with open(self.getLogFilename(), 'a') as fp:
            fp.writelines(dataLines)
        # Write to memory
        for r in readings:
            for f in self.__fields:
                if r['device'] not in self.data[f]:
                    self.data[f][r['device']] = ([], [])
                
                deviceData = self.data[f][r['device']]
                deviceData[0].append(timeValue)
                del deviceData[0][:-self.__numPoints]
                deviceData[1].append(r[f])
                del deviceData[1][:-self.__numPoints]
        # Write to global variable
        latestData.clear()
        for r in readings:
            latestData[r['device']] = r
            latestData[r['device']]['time'] = timeString
        
        # Update figure after reading
        self.updateFigure()
    
    def timedLoop(self, event):
        # self.getReadings()
        # self.updateFigure()
        self.readingWorker = ReaderThread(self)

    def onClose(self, event):
        self.worker.abort()
        self.readingWorker.abort()
        self.Destroy()


def main() -> None:
    """Main entrance of program.
    """
    # Configure loggers
    today = datetime.date.today().isoformat()
    basePath = os.path.abspath('.')
    logPath = os.path.join(basePath, 'logs', f'operation-{today}.log')
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
        filename=logPath,
        level=logging.DEBUG,
        filemode='a'
        )
    # Redirect stream outputs
    stdoutLogger = logging.getLogger('STDOUT')
    sys.stdout = StreamToLoggerAndUi(stdoutLogger, None, logging.INFO)
    stderrLogger = logging.getLogger('STDERR')
    sys.stderr = StreamToLoggerAndUi(stderrLogger, None, logging.ERROR)
    # Create window and app
    app = wx.App()
    frame = ViewerFrame()
    app.SetTopWindow(frame)
    app.SetExitOnFrameDelete(True)
    frame.Show()
    app.MainLoop()

if __name__ == '__main__':
    main()
