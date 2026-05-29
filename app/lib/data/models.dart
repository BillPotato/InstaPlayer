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

class TrackDto {
  TrackDto({
    required this.id,
    this.isrc,
    required this.title,
    required this.artist,
    required this.album,
    required this.albumArtist,
    this.trackNumber,
    this.discNumber,
    this.durationMs,
    required this.fileSize,
    required this.mime,
    this.quality,
    required this.hasArt,
    required this.hasLyrics,
  });

  final String id;
  final String? isrc;
  final String title;
  final String artist;
  final String album;
  final String albumArtist;
  final int? trackNumber;
  final int? discNumber;
  final int? durationMs;
  final int fileSize;
  final String mime;
  final String? quality;
  final bool hasArt;
  final bool hasLyrics;

  factory TrackDto.fromJson(Map<String, dynamic> j) => TrackDto(
        id: _str(j['id']),
        isrc: _strOrNull(j['isrc']),
        title: _str(j['title']),
        artist: _str(j['artist']),
        album: _str(j['album']),
        albumArtist: _str(j['album_artist']),
        trackNumber: _intOrNull(j['track_number']),
        discNumber: _intOrNull(j['disc_number']),
        durationMs: _intOrNull(j['duration_ms']),
        fileSize: _int(j['file_size']),
        mime: _str(j['mime'], 'audio/flac'),
        quality: _strOrNull(j['quality']),
        hasArt: _bool(j['has_art']),
        hasLyrics: _bool(j['has_lyrics']),
      );
}

class PlaylistDto {
  PlaylistDto({
    required this.id,
    required this.name,
    this.spotifyUrl,
    required this.trackCount,
  });

  final String id;
  final String name;
  final String? spotifyUrl;
  final int trackCount;

  factory PlaylistDto.fromJson(Map<String, dynamic> j) => PlaylistDto(
        id: _str(j['id']),
        name: _str(j['name']),
        spotifyUrl: _strOrNull(j['spotify_url']),
        trackCount: _int(j['track_count']),
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
    this.playlistId,
  });

  final String id;
  final String status; // queued | running | completed | failed
  final int total;
  final int completed;
  final String? current; // label of the track being fetched, if known
  final String? error;
  final String? playlistId;

  bool get isTerminal => status == 'completed' || status == 'failed';

  factory JobDto.fromJson(Map<String, dynamic> j) => JobDto(
        id: _str(j['id'] ?? j['jobId']),
        status: _str(j['status'], 'queued'),
        total: _int(j['total']),
        completed: _int(j['completed']),
        current: _strOrNull(j['current']),
        error: _strOrNull(j['error']),
        playlistId: _strOrNull(j['playlist_id'] ?? j['playlistId']),
      );
}
