import socket
import select
import struct
import math
import threading
from datetime import datetime
from datetime import timedelta
from bitarray import bitarray

from peer import Peer
import strategy
import filesystem

class PeerManager:
    peers = {}
    info_hash : bytes
    peer_id : bytes

    keepalivetime : datetime.time
    keepalivedelta = timedelta(seconds=30)

    requesttime : datetime.time
    requestdelta = timedelta(seconds=10)

    bf = bitarray
    fs: filesystem.FileSystem

    pieces = []

    max_requests = 50
    requests = 0

    downloaders = []

    peerslock = threading.Lock()

    def __init__(self, info_hash, peer_id, fs) -> None:
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.fs = fs

        bits =  ""
        for i in range(0, fs.piece_count):
            self.pieces.append(strategy.Piece(i))
            if fs.is_piece_full(i):
                bits += '1'
            else:
                bits += '0'
        self.bf = bitarray(bits)
        self.bf.fill()

        self.keepalivetime = datetime.now() + self.keepalivedelta
        self.requesttime = datetime.now()

    def connPeer(self, peerobj):
        peerscopy = self.peers.copy()
        for k in peerscopy:
            if peerscopy[k].peer_ip == peerobj.peer_ip and peerscopy[k].peer_port == peerobj.peer_port:
                return None
        connected = peerobj.connect()
        if connected:
            peerobj.bf = bitarray(self.fs.piece_count)
            peerobj.bf.fill()
            peerobj.expiretime = datetime.now() + timedelta(minutes=2)
            self.peerslock.acquire()
            self.peers[peerobj.s.fileno()] = peerobj
            self.peerslock.release()
            self.sendHandshake(peerobj)
            return peerobj.s
        else:
            return None

    def dropPeer(self, ps):
        self.peerslock.acquire()
        if ps.fileno() in self.peers:
            #print('Dropping', self.peers[ps.fileno()].peer_ip)
            if self.peers[ps.fileno()] in self.downloaders:
                self.downloaders.remove(self.peers[ps.fileno()])
            del self.peers[ps.fileno()]
        self.peerslock.release()

    def sendHandshake(self, peerobj):
        peerobj.state = 1
        data = (b'\x13', bytes("BitTorrent protocol", 'utf-8'), bytes("\0\0\0\0\0\0\0\0", 'utf-8'), self.info_hash, self.peer_id)
        self.sendMessage(peerobj, data)

    def sendKeepalive(self, peerobj):
        data = [struct.pack('!I', 0)]
        self.sendMessage(peerobj, data)

    def sendChoke(self, peerobj):
        peerobj.am_choking = 1
        data = (struct.pack('!I', 1), b'\x00')
        self.sendMessage(peerobj, data)

    def sendUnchoke(self, peerobj):
        peerobj.am_choking = 0
        data = (struct.pack('!I', 1), b'\x01')
        self.sendMessage(peerobj, data)

    def sendInterested(self, peerobj):
        peerobj.am_interested = 1
        data = (struct.pack('!I', 1), b'\x02')
        self.sendMessage(peerobj, data)

    def sendNotInterested(self, peerobj):
        peerobj.am_interested = 0
        data = (struct.pack('!I', 1), b'\x03')
        self.sendMessage(peerobj, data)

    def sendHave(self, peerobj, index):
        data = (struct.pack('!I', 5), b'\x04', struct.pack('!I', index))
        self.sendMessage(peerobj, data)

    def sendBitfield(self, peerobj):
        peerobj.state = 2
        bf = bytes(self.bf)
        data = (struct.pack('!I', (1 + len(bf))), b'\x05', bf)
        self.sendMessage(peerobj, data)

    def sendRequest(self, peerobj, index, begin, length):
        data = (struct.pack('!I', 13), b'\x06', struct.pack('!I', index), struct.pack('!I', begin), struct.pack('!I', length))
        self.sendMessage(peerobj, data)

    def sendPiece(self, peerobj, index, begin, block):
        #print('Sending piece to', peerobj)
        data = (struct.pack('!I', (9 + len(block))), b'\x07', struct.pack('!I', index), struct.pack('!I', begin), block)
        self.sendMessage(peerobj, data)

    def processHandshake(self, message, peerobj):
        pstrlen = message[0]
        pstr = message[1:pstrlen+1]
        info_hash = message[pstrlen+9:pstrlen+29]
        peer_id = message[pstrlen+29:pstrlen+49]

        #print(pstrlen, pstr, info_hash, peer_id)

        if info_hash != self.info_hash:
            #print('Info hash did not match')
            self.dropPeer(peerobj.s)
            return

        #if peer_id != peerobj.peer_id:
            #print('Peer id did not match expected value')
            #self.dropPeer(peerobj.s)
            #return

        if peerobj.state == 0:
            self.sendHandshake(peerobj)
        
        self.sendBitfield(peerobj)

    def processChoke(self, message, peerobj):
        peerobj.peer_choking = 1

    def processUnchoke(self, message, peerobj):
        peerobj.peer_choking = 0

    def processInterested(self, message, peerobj):
        peerobj.peer_interested = 1

    def processNotInterested(self, message, peerobj):
        peerobj.peer_interested = 0

    def processHave(self, message, peerobj):
        mid = message[0]
        index = int.from_bytes(message[1:], "big")

        try:
            peerobj.bf[index] = 1
        except IndexError:
            pass
            #print('Received invalid index from', peerobj.peer_ip)

    def processBitfield(self, message, peerobj):
        mid = message[0]
        data = message[1:]

        bf = bitarray()
        bf.frombytes(data)
        #print(bf)

        if(len(bf) != len(self.bf)):
            #print("Got wrong bitfield length")
            self.dropPeer(peerobj.s)
            return

        peerobj.bf = bf
        peerobj.state = 3

    def processRequest(self, message, peerobj):
        mid = message[0]
        index = int.from_bytes(message[1:5], "big")
        begin = int.from_bytes(message[5:9], "big")
        length = int.from_bytes(message[9:], "big")

        block = self.fs.retrieve(index, begin, length)
        if block != None:
            self.sendPiece(peerobj, index, begin, block)

    def processPiece(self, message, peerobj):
        mid = message[0]
        index = int.from_bytes(message[1:5], "big")
        begin = int.from_bytes(message[5:9], "big")
        data = message[9:]

        block = (index, begin, len(data))
        #print('Received block', block)
        if block in self.pieces[index].blocks:
            self.fs.store(index, begin, data)
            self.pieces[index].recvBlock((index, begin, len(data)))

            if self.pieces[index].downloaded() == 1:
                if self.fs.is_piece_full(index):
                    #print(index, 'verified')
                    self.pieces[index].verified()
                    self.bf[index] = 1
                    peerobj.record_download(self.fs.piece_length,  (datetime.now() - self.pieces[index].starttime))
                    self.makeHave(index)
                    self.requests -= 1
                else:
                    self.pieces[index].downloadFailed()
                    #print(index, 'did not match checksum')

                self.makeRequest(peerobj)
        else:
            pass
            #print('Unexpected block received')

    def makeHave(self, index):
        self.peerslock.acquire()
        peerscopy = self.peers.copy()
        self.peerslock.release()
        for k in peerscopy:
            if peerscopy[k].state == 3:
                self.sendHave(peerscopy[k], index)

    def makeRequest(self, peerobj):
        self.requests += 1
        piece = strategy.randomPiece(peerobj.bf, self.pieces)
        if piece != None:
            blocks = self.fs.get_next_blocks_in_piece(math.ceil(self.fs.piece_length / 16384), piece.index)
            piece.downloading(peerobj, blocks)
            #print('Requesting', piece.index, 'from', peerobj.peer_ip)
            for block in blocks:
                index, begin, length = block
                self.sendRequest(peerobj, index, begin, length)

    def makeRequests(self):
        self.requesttime = datetime.now() + self.requestdelta
        self.requests -= strategy.cancelExpiredRequests(self.pieces)
        self.peerslock.acquire()
        peerscopy = self.peers.copy()
        self.peerslock.release()
        for k in peerscopy:
            peerobj = peerscopy[k]
            if self.requests <= self.max_requests and peerobj.state == 3 and peerobj.am_interested == 1 and peerobj.peer_choking == 0 and not strategy.pieces_contains(self.pieces, peerobj):
                self.makeRequest(peerobj)

    def sendMessage(self, peerobj, data):
        message = b''
        for field in data:
            message += field

        #print('Sending', message, 'to', peerobj.s.fileno())
        try:
            peerobj.s.send(message)
        except Exception:
            #print("Could not send to", peerobj.peer_ip)
            self.dropPeer(peerobj.s)
        except timeout:
            self.dropPeer(peerobj.s)

    def recvMessage(self, message, ps):
        #print('Recv from', ps.fileno(), message)
        self.peerslock.acquire()
        if ps.fileno() not in self.peers:
            ip, port = ps.getpeername()
            peerobj = Peer(None, ip, port)
            peerobj.s = ps
            peerobj.connected = True
            peerobj.bf = bitarray(self.fs.piece_count)
            peerobj.bf.fill()
            self.peers[ps.fileno()] = peerobj
            #print('Peer connected to us:', peerobj)
        self.peerslock.release()
        
        peerobj = self.peers[ps.fileno()]
        peerobj.expiretime = datetime.now() + timedelta(minutes=2)
        peerobj.message += message
        self.processPeer(peerobj)

    def processPeer(self, peerobj):
        #print("Message at", peerobj.s.fileno(), peerobj.message)
        if peerobj.expected_len == None:
            if len(peerobj.message) >= 4:
                if peerobj.state <= 1:
                    peerobj.expected_len = peerobj.message[0] + 49
                    #print('Expecting handshake of len', peerobj.expected_len, 'from', peerobj.peer_ip)
                else:
                    peerobj.expected_len = int.from_bytes(peerobj.message[0:4], "big") + 4
                    #print('Expecting message of len', peerobj.expected_len, 'from', peerobj.peer_ip)
        if peerobj.expected_len != None and len(peerobj.message) >= peerobj.expected_len:
            self.processMessage(peerobj.message[:peerobj.expected_len], peerobj)
            if len(peerobj.message) > peerobj.expected_len:
                peerobj.message = peerobj.message[peerobj.expected_len:]
                peerobj.expected_len = None
                self.processPeer(peerobj)
            else:
                peerobj.message = b''
                peerobj.expected_len = None

    def processMessage(self, message, peerobj):
        #print('Processing from', peerobj.peer_id, message, len(message))
        if len(message) > 4:
            mid = message[4]
            if peerobj.state <= 1:
                #print("Handshake from", peerobj.peer_ip)
                self.processHandshake(message, peerobj)
            elif mid == 0:
                #print("Choke from", peerobj.peer_ip)
                self.processChoke(message[4:], peerobj)
            elif mid == 1:
                #print("Unchoke from", peerobj.peer_ip)
                self.processUnchoke(message[4:], peerobj)
            elif mid == 2:
                #print("Interested from", peerobj.peer_ip)
                self.processInterested(message[4:], peerobj)
            elif mid == 3:
                #print("Not Interested from", peerobj.peer_ip)
                self.processNotInterested(message[4:], peerobj)
            elif mid == 4:
                #print("Have from", peerobj.peer_ip)
                self.processHave(message[4:], peerobj)
            elif mid == 5 and peerobj.state == 2:
                #print("Bitfield from", peerobj.peer_ip)
                self.processBitfield(message[4:], peerobj)
            elif mid == 6 and peerobj.am_choking == 0:
                #print("Request from", peerobj.peer_ip)
                self.processRequest(message[4:], peerobj)
            elif mid == 7:
                #print("Piece from", peerobj.peer_ip)
                self.processPiece(message[4:], peerobj)
            else:
                pass
                #print('Unknown message from', peerobj.peer_ip)    

    def choking(self):
        self.peerslock.acquire()
        peerscopy = self.peers.copy()
        self.peerslock.release()
        for k in peerscopy:
            peer = peerscopy[k]
            if peer.state == 3:
                #Interested/Not interested
                pieces = ~self.bf & peer.bf
                if 1 in pieces and peer.am_interested == 0:
                    self.sendInterested(peer)
                elif not 1 in pieces and peer.am_interested == 1:
                    self.sendNotInterested(peer)

                #Choke/Unchoke
                for downloader in self.downloaders:
                    if downloader.peer_interested == 0:
                        #print('Choking', peer)
                        self.downloaders.remove(downloader)
                        self.sendChoke(downloader)
                while len(self.downloaders) < 4:
                    downloader = None
                    for k1 in peerscopy:
                        peer1 = peerscopy[k1]
                        if peer1.peer_interested == 1 and not peer1 in self.downloaders and (downloader == None or downloader.downloadrate > peer1.downloadrate):
                            downloader = peer1
                    if downloader != None:
                        #print('Unchoking', downloader)
                        self.downloaders.append(downloader)
                        self.sendUnchoke(downloader)
                    else:
                        break
            
    def update(self):
        # If it has been 10 seconds since our last request, send it again (or if we haven't sent a request yet). This is also the choke timer
        if self.requesttime <= datetime.now():
            self.choking()
            self.makeRequests()

        # Send keepalives every 2 seconds
        if self.keepalivetime <= datetime.now():
            self.peerslock.acquire()
            peerscopy = self.peers.copy()
            self.peerslock.release()
            for k in peerscopy:
                self.sendKeepalive(peerscopy[k])
                self.keepalivetime = datetime.now() + self.keepalivedelta

        # Disconnect expired peers
        expired = []
        self.peerslock.acquire()
        peerscopy = self.peers.copy()
        self.peerslock.release()
        for k in peerscopy:
            if peerscopy[k].expiretime <= datetime.now():
                expired.append(k)
        for k in expired:
            del peerscopy[k]

    def print(self):
        self.printBitfield()
        self.printPeers()

    def printBitfield(self):
        print(self.bf)

    def printPeers(self):
        self.peerslock.acquire()
        peerscopy = self.peers.copy()
        self.peerslock.release()
        totaldownloadrate = 0
        for k in peerscopy:
            totaldownloadrate += peerscopy[k].downloadrate
        print('Connected peers:', len(peerscopy), 'Download rate:', totaldownloadrate, 'b/s')
        for k in peerscopy:
            print(peerscopy[k])
