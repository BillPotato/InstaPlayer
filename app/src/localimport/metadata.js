// Dependency-free audio tag readers for local imports.
//
// parseMetadata(file) — `file` must be a local file:// expo-file-system File
// (SAF handles are read-only/seek-limited, so callers copy first). Reads only
// the byte ranges it needs via FileHandle. Never throws: any parse problem
// falls back to filename-derived metadata.
//
// Formats: FLAC (STREAMINFO/VORBIS_COMMENT/PICTURE) and MP3 (ID3v2.3/2.4 +
// frame-header duration). Everything else gets fallbacks only.

const MIME_BY_EXT = {
  flac: 'audio/flac',
  mp3: 'audio/mpeg',
  m4a: 'audio/mp4',
  aac: 'audio/mp4',
  ogg: 'audio/ogg',
  opus: 'audio/ogg',
  wav: 'audio/wav',
};

export function extOf(name) {
  const m = /\.([a-z0-9]+)$/i.exec(name || '');
  return m ? m[1].toLowerCase() : '';
}

export function mimeForExt(ext) {
  return MIME_BY_EXT[ext] || 'audio/mpeg';
}

export function fallbackMeta(name) {
  return {
    title: (name || 'Unknown').replace(/\.[a-z0-9]+$/i, ''),
    artist: 'Unknown artist',
    album: 'Local import',
    albumArtist: null,
    trackNumber: null,
    durationMs: null,
    lyrics: null,
    artBytes: null,
    artMime: null,
  };
}

export function parseMetadata(file) {
  const base = fallbackMeta(file.name);
  let handle = null;
  try {
    handle = file.open();
    const magic = readAt(handle, 0, 4);
    let parsed = null;
    if (bytesToAscii(magic) === 'fLaC') {
      parsed = parseFlac(handle);
    } else if (bytesToAscii(magic.subarray(0, 3)) === 'ID3') {
      parsed = parseId3(handle, file.size);
    } else if (extOf(file.name) === 'mp3') {
      // MP3 without an ID3v2 tag: still estimate duration from the frames.
      parsed = { durationMs: mp3Duration(handle, 0, file.size) };
    }
    return { ...base, ...stripEmpty(parsed || {}) };
  } catch {
    return base;
  } finally {
    try {
      handle?.close();
    } catch {
      // Already closed.
    }
  }
}

function stripEmpty(obj) {
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v !== null && v !== undefined && v !== '') out[k] = v;
  }
  return out;
}

function readAt(handle, offset, length) {
  handle.offset = offset;
  return handle.readBytes(length);
}

// ---------------------------------------------------------------------------
// Byte helpers
// ---------------------------------------------------------------------------

function beU32(b, o) {
  return b[o] * 0x1000000 + (b[o + 1] << 16) + (b[o + 2] << 8) + b[o + 3];
}

function leU32(b, o) {
  return b[o] + (b[o + 1] << 8) + (b[o + 2] << 16) + b[o + 3] * 0x1000000;
}

function syncsafe(b, o) {
  return ((b[o] & 0x7f) << 21) | ((b[o + 1] & 0x7f) << 14) | ((b[o + 2] & 0x7f) << 7) | (b[o + 3] & 0x7f);
}

function bytesToAscii(b) {
  let s = '';
  for (let i = 0; i < b.length; i += 1) s += String.fromCharCode(b[i]);
  return s;
}

function decodeLatin1(b) {
  return bytesToAscii(b).replace(/\0+$/, '');
}

function decodeUtf8(b) {
  let out = '';
  let i = 0;
  while (i < b.length) {
    const c = b[i];
    if (c < 0x80) {
      out += String.fromCharCode(c);
      i += 1;
    } else if (c < 0xe0) {
      out += String.fromCharCode(((c & 0x1f) << 6) | (b[i + 1] & 0x3f));
      i += 2;
    } else if (c < 0xf0) {
      out += String.fromCharCode(((c & 0x0f) << 12) | ((b[i + 1] & 0x3f) << 6) | (b[i + 2] & 0x3f));
      i += 3;
    } else {
      const cp =
        ((c & 0x07) << 18) | ((b[i + 1] & 0x3f) << 12) | ((b[i + 2] & 0x3f) << 6) | (b[i + 3] & 0x3f);
      out += String.fromCodePoint(cp);
      i += 4;
    }
  }
  return out.replace(/\0+$/, '');
}

function decodeUtf16(b, bigEndianDefault) {
  let i = 0;
  let be = bigEndianDefault;
  if (b.length >= 2) {
    if (b[0] === 0xff && b[1] === 0xfe) {
      be = false;
      i = 2;
    } else if (b[0] === 0xfe && b[1] === 0xff) {
      be = true;
      i = 2;
    }
  }
  let out = '';
  for (; i + 1 < b.length; i += 2) {
    const code = be ? (b[i] << 8) | b[i + 1] : (b[i + 1] << 8) | b[i];
    if (code !== 0) out += String.fromCharCode(code);
  }
  return out;
}

// ID3 text by encoding byte: 0 latin1, 1 UTF-16 w/ BOM, 2 UTF-16BE, 3 UTF-8.
function decodeId3Text(encoding, b) {
  switch (encoding) {
    case 1:
      return decodeUtf16(b, true);
    case 2:
      return decodeUtf16(b, true);
    case 3:
      return decodeUtf8(b);
    default:
      return decodeLatin1(b);
  }
}

// Find the end of a null terminator in `b` starting at `o` for an encoding
// (UTF-16 uses double-null). Returns [stringEnd, nextOffset].
function findTerminator(b, o, encoding) {
  const wide = encoding === 1 || encoding === 2;
  if (wide) {
    for (let i = o; i + 1 < b.length; i += 2) {
      if (b[i] === 0 && b[i + 1] === 0) return [i, i + 2];
    }
  } else {
    for (let i = o; i < b.length; i += 1) {
      if (b[i] === 0) return [i, i + 1];
    }
  }
  return [b.length, b.length];
}

// ---------------------------------------------------------------------------
// FLAC
// ---------------------------------------------------------------------------

function parseFlac(handle) {
  const out = {};
  let offset = 4;
  for (let guard = 0; guard < 64; guard += 1) {
    const head = readAt(handle, offset, 4);
    if (head.length < 4) break;
    const isLast = (head[0] & 0x80) !== 0;
    const type = head[0] & 0x7f;
    const length = (head[1] << 16) | (head[2] << 8) | head[3];
    const bodyOffset = offset + 4;

    if (type === 0 && length >= 34) {
      const b = readAt(handle, bodyOffset, 34);
      const sampleRate = (b[10] << 12) | (b[11] << 4) | (b[12] >> 4);
      const totalSamples = (b[13] & 0x0f) * 0x100000000 + beU32(b, 14);
      if (sampleRate > 0 && totalSamples > 0) {
        out.durationMs = Math.round((totalSamples / sampleRate) * 1000);
      }
    } else if (type === 4) {
      const b = readAt(handle, bodyOffset, length);
      parseVorbisComment(b, out);
    } else if (type === 6 && !out.artBytes) {
      const b = readAt(handle, bodyOffset, length);
      parseFlacPicture(b, out);
    }

    offset = bodyOffset + length;
    if (isLast) break;
  }
  return out;
}

function parseVorbisComment(b, out) {
  let o = 0;
  const vendorLen = leU32(b, o);
  o += 4 + vendorLen;
  const count = leU32(b, o);
  o += 4;
  for (let i = 0; i < count && o + 4 <= b.length; i += 1) {
    const len = leU32(b, o);
    o += 4;
    if (o + len > b.length) break;
    const entry = decodeUtf8(b.subarray(o, o + len));
    o += len;
    const eq = entry.indexOf('=');
    if (eq <= 0) continue;
    const key = entry.slice(0, eq).toUpperCase();
    const value = entry.slice(eq + 1).trim();
    if (!value) continue;
    if (key === 'TITLE' && !out.title) out.title = value;
    else if (key === 'ARTIST' && !out.artist) out.artist = value;
    else if (key === 'ALBUM' && !out.album) out.album = value;
    else if (key === 'ALBUMARTIST' && !out.albumArtist) out.albumArtist = value;
    else if (key === 'TRACKNUMBER' && !out.trackNumber) out.trackNumber = parseInt(value, 10) || null;
    else if ((key === 'LYRICS' || key === 'UNSYNCEDLYRICS') && !out.lyrics) out.lyrics = value;
  }
}

function parseFlacPicture(b, out) {
  let o = 0;
  o += 4; // picture type (front cover etc.) — accept any
  const mimeLen = beU32(b, o);
  o += 4;
  const mime = bytesToAscii(b.subarray(o, o + mimeLen));
  o += mimeLen;
  const descLen = beU32(b, o);
  o += 4 + descLen;
  o += 16; // width, height, depth, colors
  const dataLen = beU32(b, o);
  o += 4;
  if (o + dataLen <= b.length && dataLen > 0) {
    out.artBytes = b.subarray(o, o + dataLen);
    out.artMime = mime || 'image/jpeg';
  }
}

// ---------------------------------------------------------------------------
// MP3 / ID3v2
// ---------------------------------------------------------------------------

function parseId3(handle, fileSize) {
  const out = {};
  const header = readAt(handle, 0, 10);
  const verMajor = header[3];
  const tagSize = syncsafe(header, 6);
  const tagEnd = 10 + tagSize;

  if (verMajor === 3 || verMajor === 4) {
    // Whole tag in memory (bounded: embedded art rarely exceeds a few MB).
    const b = readAt(handle, 10, Math.min(tagSize, 16 * 1024 * 1024));
    let o = 0;
    if (header[5] & 0x40) {
      // Extended header: v2.3 size excludes itself (plain u32), v2.4 includes (syncsafe).
      o += verMajor === 3 ? 4 + beU32(b, 0) : syncsafe(b, 0);
    }
    while (o + 10 <= b.length) {
      const id = bytesToAscii(b.subarray(o, o + 4));
      if (!/^[A-Z0-9]{4}$/.test(id)) break; // padding
      let size = verMajor === 3 ? beU32(b, o + 4) : syncsafe(b, o + 4);
      const flags2 = b[o + 9];
      let dataStart = o + 10;
      if (verMajor === 4 && flags2 & 0x01) {
        // Data-length indicator prepended.
        dataStart += 4;
        size -= 4;
      }
      if (size <= 0 || dataStart + size > b.length) break;
      const data = b.subarray(dataStart, dataStart + size);
      readId3Frame(id, data, out);
      o = dataStart + size;
    }
  }

  const durationMs = mp3Duration(handle, tagEnd, fileSize);
  if (durationMs) out.durationMs = durationMs;
  return out;
}

function readId3Frame(id, data, out) {
  const textIds = { TIT2: 'title', TPE1: 'artist', TALB: 'album', TPE2: 'albumArtist' };
  if (id in textIds) {
    const value = decodeId3Text(data[0], data.subarray(1)).split('\0')[0].trim();
    if (value && !out[textIds[id]]) out[textIds[id]] = value;
  } else if (id === 'TRCK' && !out.trackNumber) {
    const value = decodeId3Text(data[0], data.subarray(1));
    out.trackNumber = parseInt(value, 10) || null;
  } else if (id === 'USLT' && !out.lyrics) {
    const encoding = data[0];
    // encoding(1) + language(3) + null-terminated descriptor + text
    const [, textStart] = findTerminator(data, 4, encoding);
    const value = decodeId3Text(encoding, data.subarray(textStart)).trim();
    if (value) out.lyrics = value;
  } else if (id === 'APIC' && !out.artBytes) {
    const encoding = data[0];
    const [mimeEnd, afterMime] = findTerminator(data, 1, 0); // mime is latin1
    const mime = decodeLatin1(data.subarray(1, mimeEnd));
    const afterType = afterMime + 1; // picture type byte
    const [, imageStart] = findTerminator(data, afterType, encoding);
    if (imageStart < data.length) {
      out.artBytes = data.subarray(imageStart);
      out.artMime = mime || 'image/jpeg';
    }
  }
}

const BITRATES_V1_L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320];
const BITRATES_V2_L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160];
const SAMPLE_RATES_V1 = [44100, 48000, 32000];

function mp3Duration(handle, audioStart, fileSize) {
  try {
    const b = readAt(handle, audioStart, 4096);
    for (let i = 0; i + 4 <= b.length; i += 1) {
      if (b[i] !== 0xff || (b[i + 1] & 0xe0) !== 0xe0) continue;
      const versionBits = (b[i + 1] >> 3) & 0x03; // 3=MPEG1, 2=MPEG2, 0=MPEG2.5
      const layerBits = (b[i + 1] >> 1) & 0x03; // 1=Layer III
      if (layerBits !== 1 || versionBits === 1) continue;
      const bitrateIdx = (b[i + 2] >> 4) & 0x0f;
      const rateIdx = (b[i + 2] >> 2) & 0x03;
      if (bitrateIdx === 0 || bitrateIdx === 15 || rateIdx === 3) continue;
      const mpeg1 = versionBits === 3;
      const bitrate = (mpeg1 ? BITRATES_V1_L3 : BITRATES_V2_L3)[bitrateIdx] * 1000;
      let sampleRate = SAMPLE_RATES_V1[rateIdx];
      if (versionBits === 2) sampleRate /= 2;
      if (versionBits === 0) sampleRate /= 4;
      const samplesPerFrame = mpeg1 ? 1152 : 576;

      // Xing/Info header (VBR): exact frame count.
      const mono = ((b[i + 3] >> 6) & 0x03) === 3;
      const xingOff = i + 4 + (mpeg1 ? (mono ? 17 : 32) : mono ? 9 : 17);
      if (xingOff + 12 <= b.length) {
        const tag = bytesToAscii(b.subarray(xingOff, xingOff + 4));
        if ((tag === 'Xing' || tag === 'Info') && (beU32(b, xingOff + 4) & 0x01) !== 0) {
          const frames = beU32(b, xingOff + 8);
          return Math.round(((frames * samplesPerFrame) / sampleRate) * 1000);
        }
      }
      // CBR estimate.
      if (bitrate > 0) {
        return Math.round(((fileSize - audioStart) * 8 * 1000) / bitrate);
      }
      return null;
    }
  } catch {
    // No duration is fine; playback backfills it.
  }
  return null;
}
