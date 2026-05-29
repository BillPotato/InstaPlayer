// DTOs mirroring the backend JSON shapes (see backend/app/schemas.py).

// ---- Defensive coercion helpers --------------------------------------------
// JSON from the network can surprise us (nulls, ints arriving as doubles,
// missing keys). These never hard-cast, so a bad field degrades gracefully
// instead of throwing "type 'Null' is not a subtype of type 'String'".
String _str(Object? v, [String fallback = '']) => v?.toString() ?? fallback;

String? _strOrNull(Object? v) => v?.toString();

int? _intOrNull(Object? v) {
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v);
  return null;
}

int _int(Object? v, [int fallback = 0]) => _intOrNull(v) ?? fallback;

bool _bool(Object? v, [bool fallback = false]) {
  if (v is bool) return v;
  if (v is String) return v.toLowerCase() == 'true';
  return fallback;
}

/// One track in a job manifest (see backend ManifestTrack). `n` is the index
/// used to fetch the audio (`/jobs/{id}/files/{n}`) and art (`.../art/{n}`).
class ManifestTrackDto {
  ManifestTrackDto({
    required this.n,
    this.isrc,
    required this.title,
    required this.artist,
    required this.album,
    required this.albumArtist,
    this.trackNumber,
    this.durationMs,
    required this.fileSize,
    required this.mime,
    this.quality,
    required this.hasArt,
    this.lyrics,
  });

  final int n;
  final String? isrc;
  final String title;
  final String artist;
  final String album;
  final String albumArtist;
  final int? trackNumber;
  final int? durationMs;
  final int fileSize;
  final String mime;
  final String? quality;
  final bool hasArt;
  final String? lyrics;

  factory ManifestTrackDto.fromJson(Map<String, dynamic> j) => ManifestTrackDto(
        n: _int(j['n']),
        isrc: _strOrNull(j['isrc']),
        title: _str(j['title']),
        artist: _str(j['artist']),
        album: _str(j['album']),
        albumArtist: _str(j['albumArtist']),
        trackNumber: _intOrNull(j['trackNumber']),
        durationMs: _intOrNull(j['durationMs']),
        fileSize: _int(j['fileSize']),
        mime: _str(j['mime'], 'audio/flac'),
        quality: _strOrNull(j['quality']),
        hasArt: _bool(j['hasArt']),
        lyrics: _strOrNull(j['lyrics']),
      );
}

/// A finished job's manifest: the playlist name + its tracks.
class ManifestDto {
  ManifestDto({
    required this.name,
    this.spotifyUrl,
    required this.tracks,
  });

  final String name;
  final String? spotifyUrl;
  final List<ManifestTrackDto> tracks;

  factory ManifestDto.fromJson(Map<String, dynamic> j) => ManifestDto(
        name: _str(j['name'], 'Imported playlist'),
        spotifyUrl: _strOrNull(j['spotifyUrl']),
        tracks: ((j['tracks'] as List?) ?? const [])
            .map((e) => ManifestTrackDto.fromJson((e as Map).cast<String, dynamic>()))
            .toList(),
      );
}

class JobDto {
  JobDto({
    required this.id,
    required this.status,
    required this.total,
    required this.completed,
    this.current,
    this.error,
  });

  final String id;
  final String status; // queued | running | completed | failed
  final int total;
  final int completed;
  final String? current; // label of the track being fetched, if known
  final String? error;

  bool get isTerminal => status == 'completed' || status == 'failed';

  factory JobDto.fromJson(Map<String, dynamic> j) => JobDto(
        id: _str(j['id'] ?? j['jobId']),
        status: _str(j['status'], 'queued'),
        total: _int(j['total']),
        completed: _int(j['completed']),
        current: _strOrNull(j['current']),
        error: _strOrNull(j['error']),
      );
}
