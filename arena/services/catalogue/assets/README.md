`frontpage.swf` is an original SWF 6 companion required by the Launcher download sequence. It contains a 240 × 100 frame, a white background, one ShowFrame and End; no code, fonts, external URLs or Nokia assets. The catalogue is rendered by the paired XHTML and does not embed this movie.

To regenerate the 29-byte file:

```python
from pathlib import Path
import struct
bits = '01110' + ''.join(f'{n:014b}' for n in (0, 4800, 0, 2000))
bits += '0' * (-len(bits) % 8)
rect = int(bits, 2).to_bytes(len(bits) // 8, 'big')
body = rect + struct.pack('<HH', 256, 1)
body += struct.pack('<H', 9 * 64 + 3) + bytes([255, 255, 255])
body += struct.pack('<HH', 64, 0)
Path('frontpage.swf').write_bytes(b'FWS\x06' + struct.pack('<I', 8 + len(body)) + body)
```

`arena.svg` is the original vector source for the featured icon. Export with `magick -background none arena.svg -strip PNG32:arena.png`.
