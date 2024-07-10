import bencode
import hashlib
from collections import OrderedDict


class TorrentFile(object):
    info: dict
    info_hash: bytes
    announce: str
    announce_list: list = None # we don't implement this and next 3
    creation_date: int = None
    comment: str = None
    created_by: str = None
    encoding: str = 'utf-8'
    _decoded: OrderedDict = None

    def __init__ (self, path) -> None:
        # read the file and set instance variables
        with open(path, 'rb') as f:
            torrent_file = f.read()
            torrent = bencode.decode(torrent_file)
            self._decoded = torrent
            if 'info' not in torrent:
                raise ValueError('Invalid torrent file')
            self.info = torrent['info']
            self.info_hash = hashlib.sha1(bencode.encode(self.info)).digest()
            if 'announce' not in torrent:
                raise ValueError('Invalid torrent file')
            self.announce = torrent['announce']
            if 'announce-list' in torrent:
                self.announce_list = torrent['announce-list']
            if 'creation date' in torrent:
                self.creation_date = torrent['creation date']
            if 'comment' in torrent:
                self.comment = torrent['comment']
            if 'created by' in torrent:
                self.created_by = torrent['created by']
            if 'encoding' in torrent:
                self.encoding = torrent['encoding']
    
    def __repr__ (self) -> str:
        ret = 'TorrentFile('
        for key, value in self.__dict__.items():
            if key == '_decoded':
                continue
            ret += f'{key}={repr(value)}, '
        ret = ret[:-2] + ')'
        return ret
    
    def __str__ (self) -> str:
        ret = 'TorrentFile('
        ret += str(dict(self._decoded))
        ret += ')'
        return ret
