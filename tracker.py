import socket
import urllib.parse
import urllib3
import bencode
import time
import struct
import logging

from torrentfile import TorrentFile
from peer import Peer

class Tracker():
    initilized = False
    torrent_file: TorrentFile
    interval: int
    min_interval: int
    announce_list: list
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

    def __init__(self, torrent_file: TorrentFile, peer_id: bytes, port: int) -> None:
        self.torrent_file = torrent_file
        self.peer_id = peer_id
        self.port = port
        self.left = torrent_file.info['piece length'] * len(torrent_file.info['pieces'])
        self.announce_list = []
        if torrent_file.announce_list is None:
            self.announce_list.append(torrent_file.announce)
        else:
            for announce in torrent_file.announce_list:
                self.announce_list.append(announce[0])
        logging.basicConfig(filename='tracker.log', level=logging.INFO)
        self.logger = logging.getLogger(__name__)

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
    def __init__(self, torrent_file: TorrentFile, peer_id: bytes, port: int) -> None:
        super().__init__(torrent_file, peer_id, port)

    def start_connection(self):
        if self.contact({'event': 'started'}):
            self.initilized = True
    
    def contact(self, params: dict) -> bool:
        for announce in self.announce_list:
            if self.request(announce, params, 5):
                return True
            
        return False

    def request(self, announce: str, params: dict, timeout: int) -> bool:
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
            r = self._http_request(announce, params, timeout)
        except:
            self.logger.info('Request failed')
            return False
        try:
            data = bencode.decode(r)
        except Exception as e:
            self.logger.info('Failed to decode response', e)
            return False
        if 'failure reason' in data:
            self.logger.info('Tracker returns failure')
            self.logger.info('Data: ', data)
            return False
        if 'warning message' in data:
            self.logger.info(data['warning message'])
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
                    self.logger.info('Warning: Failed when parsing a peer: ', e)
                    self.logger.info('Peer: ', peer)
                    self.logger.info('Peer Object: ', peer_obj)
                    continue

        return True
    
    def _http_request(self, url: str, params: dict, timeout: int) -> bool:
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
            self.logger.info('Failed to connect to tracker')
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
                self.logger.info('Failed to receive response')
                return False
            if not data:
                break
            response += data
        s.close()
        # get status code
        status_code = int(response.split(b' ')[1])
        if status_code != 200:
            self.logger.info('Status code is not 200')
            self.logger.info('Response:', response)
        # strip headers by finding b'\r\n\r\n'
        response = response.split(b'\r\n\r\n', 1)[1]
        return response


class UDPTracker(Tracker):
    PROTOCOL_ID: int = 0x41727101980

    connection_id: int = 0
    connection_id_time: float
    s: socket.socket

    def __init__(self, torrent_file: TorrentFile, peer_id: bytes, port: int) -> None:
        super().__init__(torrent_file, peer_id, port)

    def start_connection(self):
        self.logger.info('Starting initial connection')
        return self.contact({'event': 'started'})

    def contact(self, params: dict) -> bool: 
        id = 0
        for announce in self.announce_list:
            if self.request(id, announce, params):
                return True
            id += 1
        
        return False

    def request(self, transaction_id: int, announce: str, params: dict, timeout: int = 0) -> bool:
        self.logger.info(f'Sending request to {announce}')
        #if not timeout <= 0:
            #print('UDPTracker: Warning: timeout ignored as UDP tracker protocol defines timeout')
        
        # set up socket
        host = urllib3.util.parse_url(announce).host
        port = urllib3.util.parse_url(announce).port
        if port is None:
            port = 6969
        
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((host, port))
        except socket.gaierror as err:
            self.logger.info(f'Invalid announce link {announce} {err}')
            return False

        # connect
        if self.connection_id == 0 or time.time() - self.connection_id_time > 3600:
            if not self._connect(s, transaction_id):
                self.logger.info('Failed to connect to tracker')
                s.close()
                return False

        # announce
        if not self._announce(s, transaction_id, params):
            self.logger.info('Failed to announce to tracker')
            s.close()
            return False
        
        s.close()
        return True

    def _connect(self, s: socket, transaction_id: int) -> bool:
        self.logger.info('Connecting to tracker')
        self._connect_request(s, transaction_id)
        response = self._udp_recv(s, 15)
        if response is None:
            self.logger.info('Timeout in connect')
            return False
        if not self._connect_response(transaction_id, response):
            self.logger.info('Bad response')
            return False
        
        return True

    def _announce(self, s: socket, transaction_id: int, params: dict) -> None:
        self._announce_request(s, transaction_id, params)
        response = self._udp_recv(s, 15)
        if response is None:
            self.logger.info('Timeout in announce')
            return False
        if not self._announce_response(transaction_id, response):
            return False
        
        return True

    def _connect_request(self, s: socket, transaction_id: int) -> None:
        data = struct.pack('!qii', UDPTracker.PROTOCOL_ID, 0, transaction_id)
        s.send(data)

    def _connect_response(self, transaction_id: int, data: bytes) -> bool:
        if data is None:
            self.logger.info('Data is None, probably timeout')
            return False
        if len(data) != 16:
            self.logger.info('Invalid response length')
            return False
        action, transaction_id_r, connection_id = struct.unpack('!iiq', data)
        if transaction_id_r != transaction_id or action != 0:
            self.logger.info(f'Invalid action or transaction id: transaction_id_r={transaction_id_r} transaction_id={transaction_id} action={action}')
            return False
        self.connection_id = connection_id
        self.connection_id_time = time.time()
        return True
    
    def _announce_request(self, s: socket, transaction_id: int, params: dict) -> None:
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
        
        data += struct.pack('!20s20sqqq', info_hash, str(peer_id).encode(encoding=self.torrent_file.encoding), downloaded, left, uploaded)
        data += struct.pack('!iIiih', event, ip, key, num_want, port)
        s.send(data)
    
    def _announce_response(self, transaction_id: int, data: bytes) -> bool:
        if data is None:
            self.logger.info('Data is None, probably timeout')
            return False
        if len(data) < 20:
            self.logger.info('Invalid response length')
            return False
        action, transaction_id_r, interval, leechers, seeders = struct.unpack('!iiiii', data[:20])
        if transaction_id_r != transaction_id or action != 1:
            self.logger.info(f'Invalid action or transaction id: transaction_id_r={transaction_id_r} transaction_id={transaction_id} action={action}')
            return False
        
        self.incomplete = leechers
        self.complete = seeders
        self.interval = interval

        if len(data) != 20 + 6 * (leechers + seeders):
            self.logger.info('Invalid response length')
            return False

        self.peers = []
        for i in range(leechers + seeders):
            ip, port = struct.unpack('!IH', data[20 + 6 * i: 20 + 6 * i + 6])
            ip = socket.inet_ntoa(struct.pack('!I', ip))
            peer_obj = Peer(None, ip, port)
            self.peers.append(peer_obj)
        return True

    def _udp_recv(self, s: socket, timeout: int) -> bytes:
        s.settimeout(timeout)
        data = None
        try:
            data = s.recv(4096)
        except:
            pass
        return data
