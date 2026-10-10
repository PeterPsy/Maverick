"""Generate matching vector/PNG identity: neutral line art with native icon padding."""
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1] / "frontend/public"
SIZE, SCALE = 128, 3
# Rounded chain geometry. Compact artwork occupies 52% of the transparent canvas,
# matching the rail's Material Symbols sizing rather than filling its glass tile.
LINKS = [
    [(10, 13), (12, 15), (15, 15), (17, 13), (20, 10), (22, 8), (22, 5), (20, 3), (18, 1), (15, 1), (13, 3), (11, 5)],
    [(14, 11), (12, 9), (9, 9), (7, 11), (4, 14), (2, 16), (2, 19), (4, 21), (6, 23), (9, 23), (11, 21), (13, 19)],
]

def curve(a, b, c, d):
    return [tuple((1-t)**3*a[j]+3*(1-t)**2*t*b[j]+3*(1-t)*t*t*c[j]+t**3*d[j] for j in (0,1)) for t in (i/120 for i in range(121))]

paths = []
for points in LINKS:
    a,b,c,d,e,f,g,h,i,j,k,l = points
    paths.append(curve(a,b,c,d)+curve(d,d,e,e)+curve(e,f,g,h)+curve(h,i,j,k)+curve(k,k,l,l))
# Keep the optical centre at the centre of every consuming tile.
paths = [[(64+(x-12)*2.8,64+(y-12)*2.8) for x,y in path] for path in paths]
ROOT.mkdir(exist_ok=True)
polylines = ''.join('<polyline points="'+ ' '.join(f'{x:.3f},{y:.3f}' for x,y in path)+'"/>' for path in paths)
ROOT.joinpath('maverick-icon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><g fill="none" stroke="#ececec" stroke-width="5.6" stroke-linecap="round" stroke-linejoin="round">'+polylines+'</g></svg>\n')
side = SIZE*SCALE
pixels = bytearray(side*side)
radius = 2.8*SCALE
for path in paths:
    for x,y in path:
        x,y = x*SCALE,y*SCALE
        for row in range(max(0,int(y-radius)), min(side,int(y+radius)+1)):
            for col in range(max(0,int(x-radius)), min(side,int(x+radius)+1)):
                if (col+.5-x)**2+(row+.5-y)**2 <= radius**2:
                    pixels[row*side+col] = 255
rows=[]
for y in range(SIZE):
    row=bytearray([0])
    for x in range(SIZE):
        alpha=sum(pixels[(y*SCALE+dy)*side+x*SCALE+dx] for dy in range(SCALE) for dx in range(SCALE))//(SCALE*SCALE)
        row.extend((236,236,236,alpha))
    rows.append(row)
def chunk(kind,data):
    return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
ROOT.joinpath('maverick-icon-compact.png').write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',SIZE,SIZE,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b''))
