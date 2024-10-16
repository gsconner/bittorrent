import sys
import socket
import select
import re
import struct
import timerfd
import random
import threading
import logging

import peermanager
from torrent import Torrent
from torrentfile import TorrentFile
from tracker import Tracker
from peer import Peer

def connect_to_peer(peer):
    #print('Found peer:', peer)
    ps = pm.connPeer(peer)
    if ps != None:
        #print('Connected to peer:', peer)
        ep.register(ps.fileno(), select.EPOLLIN)
        fileno_to_socket[ps.fileno()] = ps

if __name__ == "__main__":
    if (len(sys.argv) < 2):
        sys.exit("Usage: bittorrent.py <.torrent file> [port]")

    # arg1 = torrent file path
    path = sys.argv[1]
    if (path.endswith('.torrent') == False):
        sys.exit("Must be a path to a torrent file")

    # arg2 = port
    port = 0
    if (len(sys.argv) > 2):
        port = int(sys.argv[2])

    # Config logger
    logging.basicConfig(filename='bittorrent.log', level=logging.INFO)
    logging.info("Starting bittorrent")

    # Load bencoded data from torrent file
    torrent_file = TorrentFile(path)

    # Create hash list
    pieces = torrent_file.info['pieces']
    hashes = []
    for x in range (0, len(pieces),20):
        temp = bytes()
        for y in range (x, x + 20):
            val = pieces[y] & 0xff
            val = struct.pack("B",val)
            temp = temp + val
        hashes.append(temp)
    
    # Initialize torrent
    if 'files' in torrent_file.info:
        files = torrent_file.info['files']
        directory = path.rstrip('.torrent')
        for file in files:
            file_path = file['path']
            if type(file_path) != str:
                file['path'] = [directory, *file_path]
            else:
                file['path'] = [directory, file_path]
    else: 
        files = [dict(length = torrent_file.info['length'], path = torrent_file.info['name'])]

    fs = Torrent(torrent_file.info['piece length'], hashes, files)

    # Check local files
    fs.check_local_files()

    # Generate Peer ID
    peer_id = '-Rn4829-'
    for x in range(0,12):
        peer_id += str(random.randint(0,9))
    peer_id = bytes(peer_id, 'ascii')

    # Set up TCP server
    fileno_to_socket = {}

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", port))
    s.listen(50)

    ep = select.epoll()
    ep.register(sys.stdin.fileno(), select.EPOLLIN)
    ep.register(s.fileno(), select.EPOLLIN)

    # Initialize peer manager
    pm = peermanager.PeerManager(torrent_file.info_hash, peer_id, fs)

    # Initialize tracker
    tracker = Tracker(torrent_file, peer_id, 6881)
    tracker.request({'event': 'started'})
    for peer in tracker.peers:
        t = threading.Thread(target=connect_to_peer, args=(peer,))
        t.start()

    tracker_update_timer = timerfd.create(timerfd.CLOCK_REALTIME,0)
    timerfd.settime(tracker_update_timer,0,30,0)
    ep.register(tracker_update_timer, select.EPOLLIN)

    while True:
        for fileno, eventmask in ep.poll(-1):
            if fileno == sys.stdin.fileno():
                l = sys.stdin.readline()
                args = re.split(' +', l)
                if len(args) == 1:
                    if args[0] == "print\n":
                        print(fs)
                        pm.print()
                    elif args[0] == "exit\n":
                        exit()
                    else:
                        print("Invalid input")
                elif len(args) == 4:
                    if args[0] == "peer":
                        peer = Peer(args[1], args[2], int(args[3]))
                        t = threading.Thread(target=connect_to_peer, args=(peer,))
                        t.start()
                    else:
                        print("Invalid syntax")
                else:
                    print("Invalid syntax")
            elif fileno == s.fileno():
                ps, _ = s.accept()
                ep.register(ps.fileno(), select.EPOLLIN)
                fileno_to_socket[ps.fileno()] = ps
            elif fileno == tracker_update_timer:
                if tracker.request({}):
                    for peer in tracker.peers:
                        t = threading.Thread(target=connect_to_peer, args=(peer,))
                        t.start()
                timerfd.settime(tracker_update_timer,0,30,0)
            else: # Message from existing peer
                ps = fileno_to_socket[fileno]
                try:
                    message = ps.recv(17000)
                    if len(message) == 0:
                        ep.unregister(fileno)
                        del fileno_to_socket[fileno]
                        pm.dropPeer(ps)
                    else:
                        pm.recvMessage(message, ps)
                except ConnectionResetError:
                    ep.unregister(fileno)
                    del fileno_to_socket[fileno]
                    pm.dropPeer(ps)
        pm.update()