import random
from datetime import datetime
from datetime import timedelta
import bitfield

class Piece:
    starttime: datetime.time
    expiretime: datetime.time
    expiredelta = timedelta(seconds=5)
    def __init__(self, index):
        self.index = index
        self.status = 0
        self.peer = None
        self.blocks = []

    def downloading(self, peer, blocks):
        self.status = 1
        self.peer = peer
        self.blocks = blocks
        self.starttime = datetime.now()
        self.expiretime = datetime.now() + self.expiredelta

    def recvBlock(self, block):
        self.blocks.remove(block)
        self.expiretime = datetime.now() + self.expiredelta

    def downloaded(self):
        return self.blocks == []

    def downloadFailed(self):
        if self.status == 1:
            self.status = 0
            self.peer = None
    
    def verified(self):
        self.status = 2
        self.peer = None

def randomPiece(bf, pieces):
    eligible_pieces = []
    if len(bf) != len(pieces):
        return None
    for i in range(len(bf)):
        if bf[i] == 1 and pieces[i].status == 0:
            eligible_pieces.append(pieces[i])
    if len(eligible_pieces) > 0:
        return random.choice(eligible_pieces)
    else:
        return None

def pieces_contains(pieces, peer):
    for piece in pieces:
        if piece.peer == peer:
            return True
    return False

def cancelExpiredRequests(pieces):
    expired = 0
    for piece in pieces:
        if piece.status == 1 and piece.expiretime <= datetime.now():
            piece.downloadFailed()
            expired += 1
    return expired