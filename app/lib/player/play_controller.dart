import 'package:audio_service/audio_service.dart';

import '../core/api_client.dart';
import '../data/db/database.dart';
import 'audio_handler.dart';

/// Turns library tracks into a playback queue, preferring the downloaded file
/// and falling back to an authenticated stream from the backend.
class PlayController {
  PlayController(this._handler, this._api, this._db);

  final MusicAudioHandler _handler;
  final ApiClient _api;
  final AppDatabase _db;

  Future<void> playAll(List<LocalTrack> tracks, int index) async {
    if (tracks.isEmpty) return;
    final items = tracks.map(_toMediaItem).toList();
    await _handler.setQueueAndPlay(items, initialIndex: index);
    await _db.touchLastPlayed(tracks[index].id);
  }

  MediaItem _toMediaItem(LocalTrack t) {
    final isLocal = t.downloadState == DownloadState.downloaded &&
        (t.localPath != null && t.localPath!.isNotEmpty);
    return MediaItem(
      id: t.id,
      title: t.title.isEmpty ? 'Unknown title' : t.title,
      artist: t.artist,
      album: t.album,
      duration: t.durationMs != null ? Duration(milliseconds: t.durationMs!) : null,
      // Notification art is intentionally omitted: the backend art endpoint
      // needs a bearer header the notification image loader can't send. In-app
      // art is fetched with auth via cached_network_image instead.
      extras: isLocal
          ? {'localPath': t.localPath}
          : {'url': _api.fileUrl(t.id), 'headers': _api.authHeader},
    );
  }
}
