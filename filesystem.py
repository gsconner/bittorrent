import hashlib
import itertools
import math
import os
from typing import List

#John Doggett

class FileSystem:
    class piece:
        def __init__(self, size: int, hash: bytes, piece_num: int):
            self.size = size;
            self.hash = hash;
            self.piece_num = piece_num;
            self.block_data = bytearray(size)
            self.block_received = bytearray(size)
            self.full = False;

        def add_block(self, buffer: bytearray, start_pos: int) -> None:
            if (self.full == False):

                self.block_data[start_pos:min(start_pos+len(buffer),self.size)] = buffer
                self.block_received[start_pos:min(start_pos+len(buffer),self.size)] = itertools.repeat(1, min(start_pos+len(buffer),self.size) - start_pos)

                #Check if piece is now full
                for x in self.block_received:
                   if (x != 1):
                       return
                if (self.verify()):
                    self.full = True;
                    #print("Filled partition: " + str(self.piece_num))
                else:
                    self.block_data = bytearray(self.size)
                    self.block_received = bytearray(self.size)

        def get_block(self,start_pos: int, size: int) -> bytearray:
            end = min(start_pos + size, self.size)
            if (self.full):
                return self.block_data[start_pos:end]
            return None

        def verify(self) -> bool:
            m = hashlib.sha1();
            m.update(self.block_data);
            return (m.digest() == self.hash);

        def is_full(self) -> bool:
            return self.full;

        #                               Partition Num, 0th offset, length
        def next_blocks(self, num: int):
            output = [];
            if (self.full == False):
                for index in range(0, self.size, 16384):
                    if (num <= 0):
                        return output;
                    gotten = True;
                    for y in range(index, min(index + 16384, self.size)):
                        if (self.block_received[y] == 0) :
                            gotten = False;
                            break;
                    if (gotten == False):
                        request = (self.piece_num, index, min(index + 16384, self.size) - index)
                        output.append(request)
                        num = num - 1;
            return output;
  
    def __init__(self, torrent_size: int, piece_length: int, hash_list: List[bytes], file_name: str):
        self.torrent_size = torrent_size;
        self.piece_length = piece_length;
        self.file_name = file_name;
        self.piece_list = [];
        self.is_full = False;
        

        #Calculate number of pieces
        num_pieces = math.ceil(torrent_size / piece_length);
        self.piece_count = num_pieces;
        #Create pieces
        remaining = torrent_size;
        for x in range(num_pieces):
            self.piece_list.append(FileSystem.piece(min(remaining,piece_length), hash_list[x], x))
            remaining = remaining - piece_length;
        
        #Read existing file
        if (os.path.exists(file_name)):
            #Easy check if file length != torrent_size
            if (os.stat(file_name).st_size == self.torrent_size):
                #Read the file, copy to data structure.
                f = open(file_name, "rb");
                for x in self.piece_list:
                    temp_bytes = f.read(x.size)
                    x.add_block(temp_bytes,0);
                
                #Check if everyblock is valid
                self.is_full = True;

                for x in self.piece_list:
                    if (x.is_full == False):
                        self.is_full = False;
                        f.close()
                        break;
                f.close()
                print("TORRENT FULLY DOWNLOADED!")


                        
    def store(self, piece_number: int, piece_offset: int, data: bytearray) -> None:
        if (self.is_full == False):
            if piece_number in range(len(self.piece_list)):
                self.piece_list[piece_number].add_block(data, piece_offset);
            
            #Write to disk once full!
            if (self.__check_if_full()):
                f = open(self.file_name, "wb");
                for x in self.piece_list:
                    f.write(x.block_data);
                f.close();
                print("TORRENT FULLY DOWNLOADED!")

    def retrieve(self, piece_number: int, piece_offset: int, data_length: int) -> bytearray:
        if piece_number in range(len(self.piece_list)):
            return self.piece_list[piece_number].get_block(piece_offset, data_length);
        return None;
    
    def is_piece_full(self, piece_number: int) -> bool:
        if piece_number in range(len(self.piece_list)):
            return self.piece_list[piece_number].is_full();
        return False;

    #                                   Partition Num, 0th offset, length
    def get_next_blocks(self, num_blocks: int):
        remaining = num_blocks;
        output = [];
        if (self.is_full == False):
            for x in self.piece_list:
                if (remaining <= 0):
                   break;
                if (x.is_full == False):
                    temp = x.next_blocks(remaining);
                    output.extend(temp);
                    remaining = remaining - len(temp);
        return output;

    #                                                           Partition Num, 0th offset, length
    def get_next_blocks_in_piece(self, num_blocks: int, piece_number: int):
        if piece_number in range(len(self.piece_list)):
            return self.piece_list[piece_number].next_blocks(num_blocks);
        return None;

    def __check_if_full(self) -> bool:
        for x in self.piece_list:
            if (x.is_full() == False):
                self.is_full = False;
                return False;
        self.is_full = True;
        return True;

    def get_non_full_pieces(self) -> List[int]:
        output = []
        for index, x, in enumerate(self.piece_list):
            if (x.is_full == False):
                output.append(index);
        return output;

    def print(self) -> None:
        total = 0;
        for x in self.piece_list:
            if (x.is_full()):
                total = total + 1
        print("Filesystem Percentage Verified: " + str(total / self.piece_count));
