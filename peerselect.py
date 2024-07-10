import select

from peer import Peer


def peer_select(peers: list[Peer], read_timeout: int = 5) -> tuple[list[Peer], list[Peer]]:
    """
    Polls peers, returns tuple of peers ready to read and peers ready to write
    """
    connected_peers = {}
    for peer in peers:
        if peer.connected:
            connected_peers[peer.s] = peer
    if len(connected_peers) == 0:
        return [], []
    
    read_sockets, _, _ = select.select(connected_peers.keys(), [], [], read_timeout)
    _, write_sockets, _ = select.select([], connected_peers.keys(), [], 0)
    read_peers = [connected_peers[socket] for socket in read_sockets]
    write_peers = [connected_peers[socket] for socket in write_sockets]
    return read_peers, write_peers
