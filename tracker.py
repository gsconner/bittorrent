import socket
import urllib.parse
import urllib3
import bencode
import time
import struct

from torrentfile import TorrentFile
from peer import Peer

class Tracker():
    initilized = False
    torrent_file: TorrentFile
    interval: int
    min_interval: int
    tracker_id: str
    # tracker_address: str
    # tracker_port: int
    complete: int
    incomplete: int
    # following used for sending requests
    port: int
    peer_id: str
    downloaded = 0 # modify on download/upload
    uploaded = 0
    left: int
    compact = 0
    no_peer_id = 0
    ip = None
    # Do not use this super class, use HTTPTracker for now

    def __init__(self, torrent_file: TorrentFile, peer_id: str, port: int) -> None:
        self.torrent_file = torrent_file
        self.peer_id = peer_id
        self.port = port
        self.left = torrent_file.info['piece length'] * len(torrent_file.info['pieces'])

    def __repr__(self) -> str:
        ret = 'Tracker('
        for key, value in self.__dict__.items():
            ret += f'{key}={repr(value)}, '
        ret = ret[:-2] + ')'
        return ret

    def request(self, params: dict, timeout: int) -> bool:
        raise NotImplementedError
    
    @staticmethod
    def tracker_type(announce: str):
        if announce.startswith('http://'):
            return HTTPTracker
        elif announce.startswith('udp://'):
            return UDPTracker
        elif announce.startswith('https://'):
            raise NotImplementedError
        else:
            raise ValueError('Invalid tracker type')


class HTTPTracker(Tracker):
    def __init__(self, torrent_file: TorrentFile, peer_id: str, port: int) -> None:
        super().__init__(torrent_file, peer_id, port)
        if self.request({'event': 'started'}, 5):
            self.initilized = True

    def request(self, params: dict, timeout: int) -> bool:
        if 'info_hash' not in params:
            params['info_hash'] = self.torrent_file.info_hash
        if 'peer_id' not in params:
            params['peer_id'] = self.peer_id
        if 'port' not in params:
            params['port'] = self.port
        if 'uploaded' not in params:
            params['uploaded'] = self.uploaded
        if 'downloaded' not in params:
            params['downloaded'] = self.downloaded
        if 'left' not in params:
            params['left'] = self.left
        if 'compact' in params:
            raise NotImplementedError
        if 'no_peer_id' not in params:
            params['no_peer_id'] = self.no_peer_id
        if 'ip' not in params and self.ip is not None:
            params['ip'] = self.ip
        
        # send request
        try:
            r = HTTPTracker._http_request(self.torrent_file.announce, params, timeout)
        except:
            print('Tracker: request failed')
            return False
        try:
            # print(r)
            data = bencode.decode(r)
        except Exception as e:
            print('Tracker: Failed to decode response', e)
            return False
        if 'failure reason' in data:
            print('Tracker: Tracker returns Failure')
            print('Data: ', data)
            return False
        if 'warning message' in data:
            print(data['warning message'])
        if 'interval' in data:
            self.interval = data['interval']
        if 'min interval' in data:
            self.min_interval = data['min interval']
        if 'tracker id' in data:
            self.tracker_id = data['tracker id']
        if 'complete' in data:
            self.complete = data['complete']
        if 'incomplete' in data:
            self.incomplete = data['incomplete']
        if 'peers' in data:
            self.peers = []
            for peer in data['peers']:
                peer_obj = None
                try:
                    if 'peer id' in peer:
                        peer_obj = Peer(peer['peer id'], peer['ip'], peer['port'])
                    else:
                        peer_obj = Peer(None, peer['ip'], peer['port'])
                    self.peers.append(peer_obj)
                except ValueError as e:
                    print('Tracker: Warning: Failed when parsing a peer: ', e)
                    print('Peer: ', peer)
                    print('Peer Object: ', peer_obj)
                    continue

        return True
    
    @staticmethod
    def _http_request(url: str, params: dict, timeout: int) -> bool:
        server_host = urllib3.util.parse_url(url).host
        server_port = urllib3.util.parse_url(url).port
        url_path = urllib3.util.parse_url(url).path
        url_query = urllib.parse.urlencode(params)
        if server_port is None:
            server_port = 80
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((server_host, server_port))
        except:
            print('Tracker: Failed to connect to tracker')
            return False
        # send request
        request = 'GET ' + url_path + '?' + url_query + ' HTTP/1.1\r\n'
        request += 'Host: ' + server_host + '\r\n'
        request += 'Connection: close\r\n'
        request += '\r\n'
        s.send(request.encode())
        # receive response
        response = b''
        while True:
            try:
                data = s.recv(1024)
            except:
                print('Tracker: Failed to receive response')
                return False
            if not data:
                break
            response += data
        s.close()
        # get status code
        status_code = int(response.split(b' ')[1])
        if status_code != 200:
            print('Tracker: Status code is not 200')
            print('Tracker: Response:', response)
        # strip headers by finding b'\r\n\r\n'
        response = response.split(b'\r\n\r\n', 1)[1]
        return response


class UDPTracker(Tracker):
    PROTOCOL_ID: int = 0x41727101980

    connection_id: int = 0
    connection_id_time: float
    tracker_ip: str
    tracker_port: int
    s: socket.socket

    def __init__(self, torrent_file: TorrentFile, peer_id: str, port: int) -> None:
        super().__init__(torrent_file, peer_id, port)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # parst udp://host:port
        self.tracker_ip = urllib3.util.parse_url(self.torrent_file.announce).host
        self.tracker_port = urllib3.util.parse_url(self.torrent_file.announce).port
        if self.tracker_port is None:
            self.tracker_port = 6969
        # set destination
        self.s.connect((self.tracker_ip, self.tracker_port))
        # send initial request
        if self.request({'event': 'started'}):
            self.initilized = True
        else:
            print('UDPTracker: Failed to initialize')
            self.initilized = False


    def request(self, params: dict, timeout: int = 0) -> bool:
        if not timeout <= 0:
            print('UDPTracker: Warning: timeout ignored as UDP tracker protocol defines timeout')
        
        # connect
        if self.connection_id == 0 or time.time() - self.connection_id_time > 3600:
            print('UDPTracker: Connecting to tracker')
            for i in range(0, 9):
                self._connect_request(i)
                response = self._udp_recv(15 * (2 ** i))
                if response is None:
                    print('UDPTracker: Timeout in connect')
                    continue
                if not self._connect_response(i, response):
                    continue
                break
            else:
                print('UDPTracker: Failed to connect to tracker')
                return False

        # announce
        for i in range(0, 9):
            self._announce_request(i, params)
            response = self._udp_recv(15 * (2 ** i))
            if response is None:
                print('UDPTracker: Timeout in announce')
                continue
            if not self._announce_response(i, response):
                continue
            break
        else:
            print('UDPTracker: Failed to announce to tracker')
            return False
        
        return True


    def _connect_request(self, transaction_id: int) -> None:
        data = struct.pack('!qii', UDPTracker.PROTOCOL_ID, 0, transaction_id)
        self.s.send(data)

    def _connect_response(self, transaction_id: int, data: bytes) -> bool:
        if data is None:
            print('UDPTracker: _connect_response: data is None, probably timeout')
            return False
        if len(data) != 16:
            print('UDPTracker: Invalid response length')
            return False
        action, transaction_id_r, connection_id = struct.unpack('!iiq', data)
        if transaction_id_r != transaction_id or action != 0:
            print('UDPTracker: Invalid action or transaction id')
            return False
        self.connection_id = connection_id
        self.connection_id_time = time.time()
        return True
    
    def _announce_request(self, transaction_id: int, params: dict) -> None:
        data = struct.pack('!qii', self.connection_id, 1, transaction_id)
        
        info_hash = self.torrent_file.info_hash
        if 'info_hash' in params:
            info_hash = params['info_hash']
        peer_id = self.peer_id
        if 'peer_id' in params:
            peer_id = params['peer_id']
        downloaded = self.downloaded
        if 'downloaded' in params:
            downloaded = params['downloaded']
        left = self.left
        if 'left' in params:
            left = params['left']
        uploaded = self.uploaded
        if 'uploaded' in params:
            uploaded = params['uploaded']
        
        event = 0
        if 'event' in params:
            if params['event'] == 'started':
                event = 1
            elif params['event'] == 'completed':
                event = 2
            elif params['event'] == 'stopped':
                event = 3
        ip = 0
        if 'ip' in params:
            # str to int
            ip = struct.unpack('!I', socket.inet_aton(params['ip']))[0]
        key = 0
        if 'key' in params:
            key = params['key']
        num_want = -1
        if 'num_want' in params:
            num_want = params['num_want']
        port = self.port
        if 'port' in params:
            port = params['port']
        
        data += struct.pack('!20s20sqqq', info_hash, peer_id.encode(encoding=self.torrent_file.encoding), downloaded, left, uploaded)
        data += struct.pack('!iIiih', event, ip, key, num_want, port)
        self.s.send(data)
    
    def _announce_response(self, transaction_id: int, data: bytes) -> bool:
        if data is None:
            print('UDPTracker: _announce_response: data is None, probably timeout')
            return False
        if len(data) < 20:
            print('UDPTracker: Invalid response length')
            return False
        action, transaction_id_r, interval, leechers, seeders = struct.unpack('!iiiii', data[:20])
        if transaction_id_r != transaction_id or action != 1:
            print('UDPTracker: Invalid action or transaction id')
            return False
        
        self.incomplete = leechers
        self.complete = seeders
        self.interval = interval

        if len(data) != 20 + 6 * (leechers + seeders):
            print('UDPTracker: Invalid response length')
            return False

        self.peers = []
        for i in range(leechers + seeders):
            ip, port = struct.unpack('!IH', data[20 + 6 * i: 20 + 6 * i + 6])
            ip = socket.inet_ntoa(struct.pack('!I', ip))
            peer_obj = Peer(None, ip, port)
            self.peers.append(peer_obj)
        return True

    def _udp_recv(self, timeout: int) -> bytes:
        self.s.settimeout(timeout)
        data = None
        try:
            data = self.s.recv(4096)
        except:
            pass
        return data
