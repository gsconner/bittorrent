class Bitfield:
    bitfield: str

    def __init__(self, bitfield):
        self.bitfield = bitfield

    def __str__(self):
        return self.bitfield
    
    def __len__(self):
        return len(self.bitfield)

    def has(self, piece):
        return (1 if self.bitfield[piece] == '1' else 0)

    def set_bit(self, index):
        if index < (len(self.bitfield)-1):
            self.bitfield = self.bitfield[0:index] + '1' + self.bitfield[index+1:]
        else:
            self.bitfield = self.bitfield[0:len(self.bitfield)-1] + '1'

    def get_zeroes(self):
        z = []
        for i in range(len(self.bitfield)):
            if self.has(i) == 0:
                z.append(i)

        return z