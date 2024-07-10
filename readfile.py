import sys
import bencode

with open(sys.argv[1], 'rb') as fs:
   torrentFile = fs.read()

if (len(sys.argv) != 2):
   sys.exit("Use: readfile.py [.torrent file here]")


torrent = bencode.decode(torrentFile)

info =torrent['info']
# print(info)

print (torrent)


