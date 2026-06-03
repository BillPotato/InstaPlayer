import 'dart:io';

import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

part 'database.g.dart';

enum DownloadState { notDownloaded, queued, downloading, downloaded, failed }

/// Local mirror of backend track metadata + per-device download state.
class LocalTracks extends Table {
  TextColumn get id => text()();
  TextColumn get isrc => text().nullable()();
  TextColumn get title => text().withDefault(const Constant(''))();
  TextColumn get artist => text().withDefault(const Constant(''))();
  TextColumn get album => text().withDefault(const Constant(''))();
  TextColumn get albumArtist => text().withDefault(const Constant(''))();
  IntColumn get trackNumber => integer().nullable()();
  IntColumn get durationMs => integer().nullable()();
  TextColumn get mime => text().withDefault(const Constant('audio/flac'))();
  TextColumn get quality => text().nullable()();
  IntColumn get fileSize => integer().withDefault(const Constant(0))();
  BoolColumn get hasArt => boolean().withDefault(const Constant(false))();
  BoolColumn get hasLyrics => boolean().withDefault(const Constant(false))();
  // Lyrics text, stored locally so it works fully offline.
  TextColumn get lyrics => text().nullable()();

  // Where to fetch the audio/art from until it's downloaded: the (temporary)
  // backend job and this track's index within that job's manifest.
  TextColumn get remoteJobId => text().nullable()();
  IntColumn get remoteIndex => integer().nullable()();

  // Offline state.
  TextColumn get localPath => text().nullable()();
  TextColumn get localArtPath => text().nullable()();
  IntColumn get downloadState =>
      intEnum<DownloadState>().withDefault(const Constant(0))();
  IntColumn get downloadedBytes => integer().withDefault(const Constant(0))();
  BoolColumn get pinned => boolean().withDefault(const Constant(false))();
  IntColumn get lastPlayedAt => integer().nullable()(); // epoch ms, for LRU

  @override
  Set<Column> get primaryKey => {id};
}

class LocalPlaylists extends Table {
  TextColumn get id => text()();
  TextColumn get name => text().withDefault(const Constant(''))();
  TextColumn get spotifyUrl => text().nullable()();
  @override
  Set<Column> get primaryKey => {id};
}

class LocalPlaylistTracks extends Table {
  TextColumn get playlistId => text()();
  TextColumn get trackId => text()();
  IntColumn get position => integer().withDefault(const Constant(0))();
  @override
  Set<Column> get primaryKey => {playlistId, trackId};
}

@DriftDatabase(tables: [LocalTracks, LocalPlaylists, LocalPlaylistTracks])
class AppDatabase extends _$AppDatabase {
  AppDatabase([QueryExecutor? e]) : super(e ?? _open());

  @override
  int get schemaVersion => 2;

  @override
  MigrationStrategy get migration => MigrationStrategy(
        onCreate: (m) => m.createAll(),
        onUpgrade: (m, from, to) async {
          // v1 stored a backend-mirrored library that streamed audio. v2 keeps
          // everything on-device with a different shape, so old rows are
          // incompatible — start from a clean slate (the user re-adds playlists).
          if (from < 2) {
            await m.deleteTable(localPlaylistTracks.actualTableName);
            await m.deleteTable(localTracks.actualTableName);
            await m.deleteTable(localPlaylists.actualTableName);
            await m.createAll();
          }
        },
      );

  // ---- queries used by the UI ----
  Stream<List<LocalTrack>> watchAllTracks() =>
      (select(localTracks)..orderBy([(t) => OrderingTerm(expression: t.title)])).watch();

  Stream<List<LocalPlaylist>> watchPlaylists() => select(localPlaylists).watch();

  Future<List<LocalTrack>> playlistTracks(String playlistId) {
    final q = select(localTracks).join([
      innerJoin(localPlaylistTracks,
          localPlaylistTracks.trackId.equalsExp(localTracks.id)),
    ])
      ..where(localPlaylistTracks.playlistId.equals(playlistId))
      ..orderBy([OrderingTerm(expression: localPlaylistTracks.position)]);
    return q.map((row) => row.readTable(localTracks)).get();
  }

  Future<LocalTrack?> trackById(String id) =>
      (select(localTracks)..where((t) => t.id.equals(id))).getSingleOrNull();

  /// Downloaded, unpinned tracks ordered least-recently-played first (LRU).
  Future<List<LocalTrack>> downloadedLru() => (select(localTracks)
        ..where((t) =>
            t.downloadState.equals(DownloadState.downloaded.index) &
            t.pinned.equals(false))
        ..orderBy([
          (t) => OrderingTerm(expression: t.lastPlayedAt, mode: OrderingMode.asc),
        ]))
      .get();

  /// Tracks not yet stored on this device (for auto-offline download).
  /// Includes never-downloaded and previously-failed; excludes downloaded and
  /// in-flight (queued/downloading) so repeated calls don't double-queue.
  Future<List<LocalTrack>> tracksNeedingDownload() => (select(localTracks)
        ..where((t) =>
            t.downloadState.equals(DownloadState.notDownloaded.index) |
            t.downloadState.equals(DownloadState.failed.index)))
      .get();

  /// A specific job's tracks that aren't on the device yet (any non-downloaded
  /// state). Used to decide when a job's files can be deleted from the backend.
  Future<List<LocalTrack>> tracksForJobNotDownloaded(String jobId) =>
      (select(localTracks)
            ..where((t) =>
                t.remoteJobId.equals(jobId) &
                t.downloadState.equals(DownloadState.downloaded.index).not()))
          .get();

  Future<void> upsertTrack(LocalTracksCompanion track) =>
      into(localTracks).insertOnConflictUpdate(track);

  Future<void> setDownloadState(String id, DownloadState state,
          {int? downloadedBytes, String? localPath, String? localArtPath}) =>
      (update(localTracks)..where((t) => t.id.equals(id))).write(
        LocalTracksCompanion(
          downloadState: Value(state),
          downloadedBytes:
              downloadedBytes == null ? const Value.absent() : Value(downloadedBytes),
          localPath: localPath == null ? const Value.absent() : Value(localPath),
          localArtPath:
              localArtPath == null ? const Value.absent() : Value(localArtPath),
        ),
      );

  /// Reset any tracks stuck in queued/downloading back to notDownloaded so
  /// downloadAllMissing() picks them up on the next app start.
  Future<void> resetStuckDownloads() => (update(localTracks)
        ..where((t) =>
            t.downloadState.equals(DownloadState.queued.index) |
            t.downloadState.equals(DownloadState.downloading.index)))
      .write(const LocalTracksCompanion(
          downloadState: Value(DownloadState.notDownloaded)));

  Future<void> touchLastPlayed(String id) =>
      (update(localTracks)..where((t) => t.id.equals(id))).write(
        LocalTracksCompanion(
            lastPlayedAt: Value(DateTime.now().millisecondsSinceEpoch)),
      );

  /// Delete one track's DB row and all of its playlist join rows.
  Future<void> deleteTrackRow(String id) async {
    await (delete(localPlaylistTracks)..where((t) => t.trackId.equals(id))).go();
    await (delete(localTracks)..where((t) => t.id.equals(id))).go();
  }

  /// Tracks belonging to [playlistId] that are not in any other playlist.
  /// Safe to delete from the device when their parent playlist is removed.
  Future<List<LocalTrack>> tracksOnlyInPlaylist(String playlistId) async {
    final joins = await (select(localPlaylistTracks)
          ..where((t) => t.playlistId.equals(playlistId)))
        .get();
    final result = <LocalTrack>[];
    for (final join in joins) {
      final elsewhere = await (select(localPlaylistTracks)
            ..where((t) =>
                t.trackId.equals(join.trackId) &
                t.playlistId.isNotValue(playlistId)))
          .get();
      if (elsewhere.isEmpty) {
        final track = await trackById(join.trackId);
        if (track != null) result.add(track);
      }
    }
    return result;
  }

  /// Delete a playlist row and all of its join rows.
  /// Does NOT touch track rows — call [tracksOnlyInPlaylist] first to get
  /// orphaned tracks and delete them via [deleteTrackRow].
  Future<void> deletePlaylistRow(String id) async {
    await (delete(localPlaylistTracks)..where((t) => t.playlistId.equals(id))).go();
    await (delete(localPlaylists)..where((t) => t.id.equals(id))).go();
  }
}

LazyDatabase _open() {
  return LazyDatabase(() async {
    final dir = await getApplicationSupportDirectory();
    final file = File(p.join(dir.path, 'library.sqlite'));
    return NativeDatabase.createInBackground(file);
  });
}
