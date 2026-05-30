import 'dart:io';

import 'package:audio_service/audio_service.dart';

import '../core/api_client.dart';
import '../data/db/database.dart';
import 'audio_handler.dart';

/// Builds a playback queue from downloaded library tracks. Audio always plays
/// from the local file — the backend keeps no copy, so only downloaded tracks
/// are playable.
class PlayController {
  PlayController(this._handler, this._api, this._db);

  final MusicAudioHandler _handler;
  // ignore: unused_field  // kept for symmetry / future use
  final ApiClient _api;
  final AppDatabase _db;

  bool _isReady(LocalTrack t) =>
      t.localPath != null && t.localPath!.isNotEmpty && File(t.localPath!).existsSync();

  Future<void> playAll(List<LocalTrack> tracks, int index) async {
    if (tracks.isEmpty) return;
    final tapped = tracks[index];
    if (!_isReady(tapped)) {
      throw StateError('Still downloading — try again in a moment');
    }
    // Queue only the downloaded tracks for gapless local playback.
    final playable = tracks.where(_isReady).toList();
    var startAt = playable.indexWhere((t) => t.id == tapped.id);
    if (startAt < 0) startAt = 0;

    final items = playable.map(_toMediaItem).toList();
    await _handler.setQueueAndPlay(items, initialIndex: startAt);
    await _db.touchLastPlayed(tapped.id);
  }

  MediaItem _toMediaItem(LocalTrack t) => MediaItem(
        id: t.id,
        title: t.title.isEmpty ? 'Unknown title' : t.title,
        artist: t.artist,
        album: t.album,
        duration: t.durationMs != null ? Duration(milliseconds: t.durationMs!) : null,
        // Notification art is omitted (the loader can't read app-private files);
        // in-app art is shown from localArtPath via TrackArt.
        extras: {'localPath': t.localPath},
      );
}
