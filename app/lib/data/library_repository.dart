import 'package:drift/drift.dart';

import '../core/api_client.dart';
import 'db/database.dart';
import 'models.dart';

/// Syncs backend metadata into the local drift mirror and exposes it to the UI.
/// The UI always reads from drift so the app works fully offline.
class LibraryRepository {
  LibraryRepository(this._api, this._db);

  final ApiClient _api;
  final AppDatabase _db;

  Stream<List<LocalTrack>> watchTracks() => _db.watchAllTracks();
  Stream<List<LocalPlaylist>> watchPlaylists() => _db.watchPlaylists();
  Future<List<LocalTrack>> playlistTracks(String id) => _db.playlistTracks(id);
  Future<LocalTrack?> track(String id) => _db.trackById(id);

  LocalTracksCompanion _toCompanion(TrackDto t) => LocalTracksCompanion(
        id: Value(t.id),
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
        hasLyrics: Value(t.hasLyrics),
      );

  /// Pull the full backend library into the local mirror. Existing download
  /// state is preserved because insertOnConflictUpdate only touches the columns
  /// present in the companion (download columns are left absent here).
  Future<void> sync() async {
    final playlists = await _api.playlists();
    await _db.batch((b) {
      for (final pl in playlists) {
        b.insert(
          _db.localPlaylists,
          LocalPlaylistsCompanion(
            id: Value(pl.id),
            name: Value(pl.name),
            spotifyUrl: Value(pl.spotifyUrl),
          ),
          onConflict: DoUpdate((_) => LocalPlaylistsCompanion(
                name: Value(pl.name),
                spotifyUrl: Value(pl.spotifyUrl),
              )),
        );
      }
    });

    for (final pl in playlists) {
      final tracks = await _api.playlistTracks(pl.id);
      var position = 0;
      for (final t in tracks) {
        await _db.upsertTrack(_toCompanion(t));
        await _db.into(_db.localPlaylistTracks).insertOnConflictUpdate(
              LocalPlaylistTracksCompanion(
                playlistId: Value(pl.id),
                trackId: Value(t.id),
                position: Value(position++),
              ),
            );
      }
    }
  }
}
