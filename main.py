import sys, time, socket, struct, threading
from PyQt6 import QtGui
from PyQt6.QtGui import QGuiApplication, QFont, QPainter, QColor, QImage, QMouseEvent
from PyQt6.QtQml import QQmlApplicationEngine, qmlRegisterType, qmlRegisterSingletonType
from PyQt6.QtQuick import QQuickPaintedItem, QQuickItem
from PyQt6.QtCore import Qt,QObject,QRectF,QRect,QSize,pyqtSlot,pyqtSignal
import zss_cmd_pb2 as zss
import zss_cmd_type_pb2 as zss_type

MC_ADDR = "225.225.225.225"
MC_PORT = 13134
SEND_PORT = 14234

# udp receiver for multicast
class UdpReceiver:
    def __init__(self, multicast_ip, port,_cb=None):
        self.multicast_ip = multicast_ip
        self.port = port
        self._cb = _cb
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.sock.bind((self.multicast_ip, self.port))
        mreq = struct.pack("4sl", socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self.sock.settimeout(0.2)
    def receive(self,stop_token):
        while True:
            if stop_token():
                break
            try:
                data, addr = self.sock.recvfrom(65535)
                if self._cb is not None:
                    self._cb(data,addr)
            except socket.timeout:
                pass
class UdpSender:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    def send(self, msg, addr):
        self.sock.sendto(msg, addr)

class InfoReceiver:
    info = {}
    selected = {}
    def __init__(self,info_cb = None):
        self.info = {}
        self.info_cb = info_cb
    def _cb(self,data,addr):
        pb_info = zss.Multicast_Status()
        pb_info.ParseFromString(data)
        pb_info.ip = addr[0]
        self.info[addr[0]] = pb_info
        if self.info_cb is not None:
            self.info_cb(pb_info.robot_id,pb_info)
class CmdSender:
    def __init__(self):
        self.udpSender = UdpSender()
        self.pb_data = zss.Robot_Command()
        pass
    # updateCommandParams(int robotID,double velX,double velY,double velR,double ctrl,bool mode,bool shoot,double power)
    def updateCommandParams(self,robotID,velX,velY,velR,ctrl,mode,shoot,power):
        self.pb_data = zss.Robot_Command()
        self.pb_data.robot_id = -1
        self.pb_data.kick_mode = zss.Robot_Command.KickMode.NONE if not shoot else (zss.Robot_Command.KickMode.CHIP if mode else zss.Robot_Command.KickMode.KICK)
        # self.pb_data.desire_power = power
        self.pb_data.kick_discharge_time = power
        self.pb_data.dribble_spin = ctrl
        self.pb_data.cmd_type = zss.Robot_Command.CmdType.CMD_VEL
        self.pb_data.cmd_vel.velocity_x = velX
        self.pb_data.cmd_vel.velocity_y = velY
        self.pb_data.cmd_vel.velocity_r = velR
        self.pb_data.comm_type = zss.Robot_Command.CommType.UDP_WIFI
        print("updateCommandParams",str(self.pb_data))

    def sendCommand(self,infoReceiver:InfoReceiver):
        # print("sendCommand",str(self.pb_data))
        for id,info in infoReceiver.selected.items():
            self.pb_data.robot_id = id
            # Serialize
            data = self.pb_data.SerializeToString()
            self.udpSender.send(data,(info.ip,SEND_PORT))


class InfoViewer(QQuickPaintedItem):
    MAX_PLAYER = 16
    drawSignal = pyqtSignal(int,zss.Multicast_Status)
    def __init__(self,parent=None):
        super().__init__(parent)
        # accept mouse event left click
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.receiverNeedStop = False
        self.infoReceiver = InfoReceiver(self.getNewInfo)
        self.cmdSender = CmdSender()
        udpRecv = UdpReceiver(MC_ADDR,MC_PORT,self.infoReceiver._cb)
        t = threading.Thread(target=udpRecv.receive,args=(lambda : self.receiverNeedStop,))
        t.start()
        self.painter = QPainter()
        self.image = QImage(QSize(int(self.width()),int(self.height())),QImage.Format.Format_ARGB32_Premultiplied)
        self.ready = False
        self.drawSignal.connect(self.paintInfo)
    @pyqtSlot()
    def close(self):
        print("closing info viewer, stop recv thread")
        self.receiverNeedStop = True
    def getNewInfo(self,n,info):
        # print("got new info ",n,info)
        if self.ready and self.painter.isActive() and n >= 0 and n < self.MAX_PLAYER:
            self.drawSignal.emit(n,info)
    def mousePressEvent(self, event: QMouseEvent) -> None:
        index = self.getAreaIndex(event.pos())
        for info in self.infoReceiver.info.values():
            if info.robot_id == index:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.infoReceiver.selected.clear()
                else :
                    if index in self.infoReceiver.selected:
                        self.infoReceiver.selected.pop(index)
                        self.drawSignal.emit(index,info)
                        return
                self.infoReceiver.selected[index] = info
                self.drawSignal.emit(index,info)
                break
    @pyqtSlot(int,zss.Multicast_Status)
    def paintInfo(self,n,info):
        # fill background
        self.painter.setPen(QColor(255,255,255))
        self.painter.setBrush(QColor(255,255,255))
        self.painter.drawRect(QRectF(self._x(n,0.0), self._y(n,0.0), self._w(n,1.0),self._h(n,1.0)))

        self.painter.setPen(QColor(0,0,0) if n not in self.infoReceiver.selected else QColor(255,0,0))
        self.painter.setBrush(Qt.BrushStyle.NoBrush)
        self.painter.setFont(QFont('Arial', 10))

        self.painter.drawRect(QRectF(self._x(n,0.05), self._y(n,0.05), self._w(n,0.9),self._h(n,0.9)))
        self.painter.drawText(QRectF(self._x(n,0.0), self._y(n,0.0), self._w(n,1.0),self._h(n,1.0)), Qt.AlignmentFlag.AlignCenter, info.ip)
        self.update(self._area(n))
    def paint(self, painter):
        if self.ready:
            painter.drawImage(QRectF(0,0,self.width(),self.height()),self.image)
        pass
    @pyqtSlot(int,int)
    def resize(self,width,height):
        self.ready = False
        if width <=0 or height <=0:
            return
        if self.painter.isActive():
            self.painter.end()
        self.image = QImage(QSize(width,height),QImage.Format.Format_ARGB32_Premultiplied)
        self.painter.begin(self.image)
        self.ready = True
    def getAreaIndex(self,pos):
        yIndex = int(pos.y()/(self.height()/self.MAX_PLAYER))
        return yIndex
    def _area(self,n):
        return QRect(int(self._x(n,0)), int(self._y(n,0)), int(self._w(n,1)),int(self._h(n,1)))
    def _x(self,n,v):
        return self.width()*(v)
    def _y(self,n,v):
        return self.height()/self.MAX_PLAYER*(n+v)
    def _w(self,n,v):
        return self.width()*(v)
    def _h(self,n,v):
        return self.height()/self.MAX_PLAYER*(v)
    @pyqtSlot(int,float,float,float,float,bool,bool,float)
    def updateCommandParams(self,robotID,velX,velY,velR,ctrl,mode,shoot,power):
        self.cmdSender.updateCommandParams(robotID,velX,velY,velR,ctrl,mode,shoot,power)
    @pyqtSlot()
    def sendCommand(self):
        self.cmdSender.sendCommand(self.infoReceiver)

def run_qt():
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.quit.connect(app.quit)
    engine.load('main.qml')
    res = app.exec()
    del engine
    sys.exit(res)

if __name__ == '__main__':
    qmlRegisterType(InfoViewer, 'ZSS', 1, 0, 'InfoViewer')

    run_qt()
    # udpSender = UdpSender()
    # while True:
    #     time.sleep(1)