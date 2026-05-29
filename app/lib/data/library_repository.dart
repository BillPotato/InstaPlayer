import 'package:drift/drift.dart';

import '../core/api_client.dart';
import 'db/database.dart';
import 'models.dart';

/// Imports a finished backend job's manifest into the local drift library.
/// The device's drift DB is the only permanent library; the UI reads from it
/// so the app works fully offline once files are downloaded.
class LibraryRepository {
  LibraryRepository(this._api, this._db);

  final ApiClient _api;
  final AppDatabase _db;

  Stream<List<LocalTrack>> watchTracks() => _db.watchAllTracks();
  Stream<List<LocalPlaylist>> watchPlaylists() => _db.watchPlaylists();
  Future<List<LocalTrack>> playlistTracks(String id) => _db.playlistTracks(id);
  Future<LocalTrack?> track(String id) => _db.trackById(id);

  /// Stable local id for a manifest track: prefer the ISRC (so the same
  /// recording added via different playlists de-dupes), else fall back to the
  /// job id + index.
  String _trackId(String jobId, ManifestTrackDto t) =>
      (t.isrc != null && t.isrc!.isNotEmpty) ? 'isrc:${t.isrc}' : '$jobId:${t.n}';

  /// Pull a finished job's manifest into the local library: create a playlist,
  /// upsert each track's metadata (preserving any existing download state), and
  /// link them. Audio/art are NOT fetched here — see DownloadManager.
  /// Returns the local playlist id.
  Future<String> importManifest(String jobId) async {
    final manifest = await _api.manifest(jobId);

    await _db.into(_db.localPlaylists).insertOnConflictUpdate(
          LocalPlaylistsCompanion(
            id: Value(jobId),
            name: Value(manifest.name),
            spotifyUrl: Value(manifest.spotifyUrl),
          ),
        );

    var position = 0;
    for (final t in manifest.tracks) {
      final id = _trackId(jobId, t);
      // Only metadata + remote source here; download-state columns are left
      // absent so an already-downloaded copy keeps its local files.
      await _db.upsertTrack(LocalTracksCompanion(
        id: Value(id),
        isrc: Value(t.isrc),
        title: Value(t.title),
        artist: Value(t.artist),
        album: Value(t.album),
        albumArtist: Value(t.albumArtist),
        trackNumber: Value(t.trackNumber),
        durationMs: Value(t.durationMs),
        mime: Value(t.mime),
        quality: Value(t.quality),
        fileSize: Value(t.fileSize),
        hasArt: Value(t.hasArt),
        hasLyrics: Value(t.lyrics != null && t.lyrics!.isNotEmpty),
        lyrics: Value(t.lyrics),
        remoteJobId: Value(jobId),
        remoteIndex: Value(t.n),
      ));
      await _db.into(_db.localPlaylistTracks).insertOnConflictUpdate(
            LocalPlaylistTracksCompanion(
              playlistId: Value(jobId),
              trackId: Value(id),
              position: Value(position++),
            ),
          );
    }
    return jobId;
  }
}
