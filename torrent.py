import hashlib
import math
import os
from typing import List

from bitarray import bitarray

BLOCK_SIZE = 16384

class ErrorTorrent(Exception):
    pass

class ErrorPiece(Exception):
    pass

class File:
    def __init__(self, file):
        self.length = file['length']
        self.path = file['path']
        if type(self.path) != str:
            self.path = os.path.join(*file['path'])
    
    @staticmethod
    def init_file_list(files) -> List:
        file_list = []
        for file in files:
            file_list.append(File(file))

        return file_list
    
    def __len__(self) -> int:
        return self.length
    
    def __repr__(self) -> str:
            return f"File(length={self.length}, path={self.path})"
    
class Piece:
    def __init__(self, length: int, hash: bytes):
        self.length = length
        self.hash = hash
        self.verified = False
        self.blocks = bytearray(length)
        self._stored_blocks = bitarray(length)

    @staticmethod
    def init_piece_list(torrent_size, piece_length, piece_count, hash_list) -> List:
        remaining = torrent_size
        piece_list = []
        for i in range(piece_count):
            piece_list.append(Piece(min(remaining, piece_length), hash_list[i]))
            remaining -= piece_length

        return piece_list

    def add_block(self, begin: int, block: bytearray) -> None:
        if len(block) + begin > self.length:
            raise ValueError(f"Data outside of bounds: begin={begin}, len(block)={len(block)}, piece_length={self.length}")
        if begin < 0:
            raise ValueError(f"Negative data offset: begin={begin}, piece_length={self.length}")
        
        if not self.verified:
            end = begin+len(block)
            if sum(self._stored_blocks[begin:end]) == 0:
                self.blocks[begin:end] = block
                self._stored_blocks[begin:end] = (bitarray('1') * len(block))
                self.verified = self.verify()
            else:
                raise ErrorPiece(f"Attempting to write over other data in piece: begin={begin}, len(block)={len(block)}, stored_blocks={self._stored_blocks}")
        else:
            raise ErrorPiece(f"Attempting to overwrite data in verified piece")

    def get_block(self, begin: int, length: int) -> bytearray:
        if length + begin > self.length:
            raise ValueError(f"Requested block outside of bounds: begin={begin}, length={length}, piece_length={self.length}")
        if begin > self.length or begin < 0:
            raise ValueError(f"Offset out of bounds: begin={begin}, piece_length={self.length}")
        
        if self.verified:
            end = begin+length
            return self.blocks[begin:end]
        else:
            raise ErrorPiece(f"Attempting to retrieve data from unverified piece")
        
    def get_free_blocks(self, count: int):
        blocks = []
        for pos in range(0, self.length, BLOCK_SIZE):
            if count <= 0:
                break
            block_length = min(BLOCK_SIZE, self.length - pos)
            if sum(self._stored_blocks[pos:pos + block_length]) == 0:
                block = (pos, block_length)
                blocks.append(block)
                count = count - 1
        
        return blocks

    def verify(self) -> bool:
        if self.verified:
            return True
        else:
            if self._stored_blocks[:] == (bitarray('1') * self.length):
                m = hashlib.sha1()
                m.update(self.blocks)
                if m.digest() == self.hash:
                    self.verified = True
                    return True
                else:
                    self._stored_blocks[:] = (bitarray('0') * self.length)
                    return False
            else:
                return False
    
    def __repr__(self) -> str:
        return f"Piece(length={self.length}, hash={self.hash}, verified={self.verified})"
    
class Torrent:
    def __init__(self, piece_length: int, hash_list: List[bytes], files: List[dict]):
        self.piece_length = piece_length
        self.file_list = File.init_file_list(files)
        self.torrent_size = sum(map(len, self.file_list))
        self.piece_count = math.ceil(self.torrent_size / self.piece_length)
        self.piece_list = Piece.init_piece_list(self.torrent_size, self.piece_length, self.piece_count, hash_list)
        self.verified = False

    def check_local_files(self):
        # If there is local data, check if it matches hash
        if self._read_local_data():
            self.verify_torrent()
            
    def store(self, index: int, begin: int, block: bytearray) -> None:
        if index > self.piece_count or index < 0:
            raise ValueError(f"Index out of bounds: index={index}, piece_count={self.piece_count}")
        
        self.piece_list[index].add_block(begin, block)

        if (self.verify_piece(index)):
            if self.verify_torrent():
                self._write_to_disk()

    def retrieve(self, index: int, begin: int, length: int) -> bytearray:
        if index > self.piece_count or index < 0:
            raise ValueError(f"Index out of bounds: index={index}, piece_count={self.piece_count}")
        
        return self.piece_list[index].get_block(begin, length)
    
    def get_free_blocks_in_piece(self, index: int, num_blocks=None):
        if num_blocks == None:
            num_blocks = math.ceil(self.piece_length / BLOCK_SIZE)
            
        piece_blocks = self.piece_list[index].get_free_blocks(num_blocks)
        for i in range(len(piece_blocks)):
            piece_blocks[i] = (index,) + piece_blocks[i]
        return piece_blocks
    
    def verify_piece(self, index: int) -> bool:
        return self.piece_list[index].verify()
    
    def verify_torrent(self) -> bool:
        if self.verified:
            return True
        else:
            for piece in self.piece_list:
                if (piece.verify() == False):
                    return False
            self.verified = True
            return True
    
    def verified_ratio(self) -> tuple[int, int]:
        total = self.piece_count
        v = 0
        for piece in self.piece_list:
            if (piece.verify() == True):
                v = v + 1
        return (v, total)
            
    def _read_local_data(self) -> bool:
        pos = 0
        modified = False
        for file in self.file_list:
            end = pos + file.length
            if os.path.exists(file.path):
                if os.stat(file.path).st_size == file.length:
                    # Reading file
                    with open(file.path, "rb") as f:
                        while pos < end: 
                            modified = True

                            index = pos // self.piece_length
                            block_offset = pos % self.piece_length

                            block_size = min([end-pos, self.piece_length-block_offset])
                            block = f.read(block_size)

                            self.piece_list[index].add_block(block_offset, block)

                            pos += block_size
            pos = end

        return modified
    
    def _write_to_disk(self) -> None:
        pos = 0
        for file in self.file_list:
            end = pos + file.length
            with open(file.path, "wb") as f:
                while pos < end:
                    index = math.floor(pos / self.piece_length)
                    block_offset = pos - index * self.piece_length

                    block_size = min([end-pos, self.piece_length-block_offset])
                    block = self.retrieve(index, block_offset, block_size)

                    f.write(block)

                    pos += block_size
        pos = end

    def __repr__(self) -> str:
        return f"Torrent(piece_length={self.piece_length}, piece_count={self.piece_count}, torrent_size={self.torrent_size}, verified={self.verified}, verified_ratio={self.verified_ratio()}, file_list={self.file_list})"