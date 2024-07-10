import socket
import datetime
import numpy as np

class Peer(object):
    context = {} # class wide variable, set with Peer.context['key'] = value

    peer_id: str
    peer_ip: str
    peer_port: int
    s: socket.socket

    am_choking = 1
    am_interested = 0
    peer_choking = 1
    peer_interested = 0

    connected = False
    state = 0

    message = b''
    expected_len = None

    bf = ''

    expiretime: datetime.time

    downloadrate = 0
    downloadrates = []

    def __init__(self, peer_id: str, peer_ip: str, peer_port: int) -> None:
        self.peer_id = peer_id
        self.peer_ip = peer_ip
        self.peer_port = peer_port
    
    def __str__(self) -> str:
        return ('Connected' if self.connected else '') + f'Peer{str(tuple(self))}' + f' {self.downloadrate} b/s'

    def __repr__(self) -> str:
        ret = ''
        # ret = 'Connected' if self.connected else ''
        ret += 'Peer('
        for key, value in self.__dict__.items():
            ret += f'{key}={repr(value)}, '
        ret = ret[:-2] + ')'
        return ret

    def __iter__(self):
        yield self.peer_id
        yield self.peer_ip
        yield self.peer_port


    def connect(self) -> bool:
        try:
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.s.settimeout(1)
            self.s.connect((self.peer_ip, self.peer_port))
            self.connected = True
        except Exception as e:
            #print(e)
            self.connected = False
        return self.connected

    def record_download(self, downloadbytes, downloadtime):
        seconds = downloadtime.total_seconds()
        self.downloadrates.append(downloadbytes/seconds)
        if len(self.downloadrates) > 100:
            self.downloadrates.pop(0)
        self.downloadrate = np.average(self.downloadrates)