import socket
import urllib.parse
import urllib3
import bencode
import time
import struct
import logging

from peer import Peer

class Tracker:
    url: str

    info_hash: str
    peer_id: bytes
    port: int

    logger: logging.Logger

    def __init__(self, url: str, info_hash: str, peer_id: bytes, port: int) -> None:
        self.url = url
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.port = port
        self.logger = logging.getLogger(__name__)

    def __repr__(self) -> str:
        ret = 'Tracker('
        for key, value in self.__dict__.items():
            ret += f'{key}={repr(value)}, '
        ret = ret[:-2] + ')'
        return ret
    
    def make_request(self, left: int, uploaded: int, downloaded: int, no_peer_id: bool, event: str = None) -> bool:
        params = {}

        params['info_hash'] = self.info_hash
        params['peer_id'] = self.peer_id
        params['port'] = self.port
        
        params['left'] = left
        params['uploaded'] = uploaded
        params['downloaded'] = downloaded
        params['no_peer_id'] = no_peer_id
        if event is not None:
            params['event'] = event
            
        self.logger.info(f'Sending request to {self.url}')
        return self._request(params)
    
    def _request(self, params) -> bool:
        raise NotImplementedError

    def _connect_socket(self, s: socket, default_port: int) -> bool:
        host = urllib3.util.parse_url(self.url).host
        port = urllib3.util.parse_url(self.url).port
        if port is None:
            port = default_port
        try:
            s.connect((host, port))
        except socket.gaierror as err:
            self.logger.info(f'Invalid announce link {self.url} {err}')
            return False
        return True
    
    @staticmethod
    def create_tracker(url: str, info_hash: str, peer_id: bytes, port: int, encoding: str):
        if url.startswith('http://'):
            return HTTPTracker(url, info_hash, peer_id, port)
        elif url.startswith('udp://'):
            return UDPTracker(url, info_hash, peer_id, port, encoding)
        elif url.startswith('https://'):
            raise NotImplementedError
        else:
            raise ValueError('Invalid tracker type')

class HTTPTracker(Tracker):
    def __init__(self, url: str, info_hash: str, peer_id: bytes, port: int) -> None:
        super().__init__(url, info_hash, peer_id, port)

    def _request(self, params: dict) -> bool:     
        r = self._send_request(params, 5)
        try:
            data = bencode.decode(r)
        except Exception as e:
            self.logger.info(f'Received response has invalid format: {e}')
            return False
        if not self._process_data(data):
            return False
        self.logger.info('Request succesful')
        return True
    
    def _send_request(self, params: dict, timeout: int) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        url = self.url
        if self._connect_socket(s, 80):
            host = urllib3.util.parse_url(url).host
            url_path = urllib3.util.parse_url(url).path
            url_query = urllib.parse.urlencode(params)
            s.settimeout(timeout)
            # send request
            request = 'GET ' + url_path + '?' + url_query + ' HTTP/1.1\r\n'
            request += 'Host: ' + host + '\r\n'
            request += 'Connection: close\r\n'
            request += '\r\n'
            s.send(request.encode())
            # receive response
            response = b''
            while True:
                try:
                    data = s.recv(1024)
                except Exception as e:
                    self.logger.info(f'Failed to receive response: {e}')
                    return False
                if not data:
                    break
                response += data
            s.close()
            # get status code
            status_code = int(response.split(b' ')[1])
            if status_code != 200:
                self.logger.info(f'Status code is not 200; Response: {response}')
            # strip headers by finding b'\r\n\r\n'
            response = response.split(b'\r\n\r\n', 1)[1]
            return response
        else:
            self.logger.info('Could not connect to tracker')
            return False
        
    def _process_data(self, data):
        if 'failure reason' in data:
            msg = data['failure reason']
            self.logger.info(f'Tracker failure: {msg}')
            return False
        if 'warning message' in data:
            msg = data['warning message']
            self.logger.info(f'Tracker warning: {msg}')
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
                    self.logger.info(f'Failed when parsing a peer: {e} Peer: {peer} Peer Object: {peer_obj}')
        return True

class UDPTracker(Tracker):
    PROTOCOL_ID: int = 0x41727101980
    connection_id: int = 0
    connection_id_time: float
    encoding: str

    def __init__(self, url: str, info_hash: str, peer_id: bytes, port: int, encoding: str) -> None:
        super().__init__(url, info_hash, peer_id, port)
        self.encoding = encoding

    def _request(self, params: dict) -> bool:
        transaction_id = 0
        # set up socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self._connect_socket(s, 6969):
            # connect
            if self.connection_id == 0 or time.time() - self.connection_id_time > 3600:
                if not self._connect(s, transaction_id):
                    s.close()
                    return False

            # announce
            if not self._announce(s, transaction_id, params):
                s.close()
                return False
            
            s.close()
            self.logger.info('Request succesful')
            return True
        else:
            self.logger.info('Failed to connect to tracker')
            return False

    def _connect(self, s: socket, transaction_id: int) -> bool:
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
        
        info_hash = params['info_hash']
        peer_id = params['peer_id']
        left = params['left']
        downloaded = params['downloaded']
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
        
        data += struct.pack('!20s20sqqq', info_hash, str(peer_id).encode(encoding=self.encoding), downloaded, left, uploaded)
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