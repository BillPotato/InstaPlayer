// Parses LRC-format lyrics ("[mm:ss.xx] line"). Returns
//   { synced: true, lines: [{ timeMs, text }] }  for timestamped lyrics
//   { synced: false, lines: [{ timeMs: 0, text }] } for plain text
//   null for empty input.
const TIME_TAG = /\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]/g;

export function parseLyrics(raw) {
  if (!raw || !raw.trim()) return null;
  const synced = [];
  const plain = [];
  for (const line of raw.split(/\r?\n/)) {
    TIME_TAG.lastIndex = 0;
    let match;
    const times = [];
    let lastIndex = 0;
    while ((match = TIME_TAG.exec(line)) !== null) {
      const minutes = parseInt(match[1], 10);
      const seconds = parseInt(match[2], 10);
      const fracRaw = match[3] || '0';
      const fracMs = Math.round(parseFloat(`0.${fracRaw}`) * 1000);
      times.push(minutes * 60000 + seconds * 1000 + fracMs);
      lastIndex = TIME_TAG.lastIndex;
    }
    const text = line.slice(lastIndex).trim();
    if (times.length) {
      for (const timeMs of times) synced.push({ timeMs, text });
    } else if (line.trim() && !/^\[[a-z]+:.*\]$/i.test(line.trim())) {
      // Skip metadata tags like [ar:Artist]; keep other plain lines.
      plain.push({ timeMs: 0, text: line.trim() });
    }
  }
  if (synced.length) {
    synced.sort((a, b) => a.timeMs - b.timeMs);
    return { synced: true, lines: synced };
  }
  if (plain.length) return { synced: false, lines: plain };
  return null;
}

export function activeLineIndex(lines, positionMs) {
  let lo = 0;
  let hi = lines.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lines[mid].timeMs <= positionMs) {
      ans = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return ans;
}
