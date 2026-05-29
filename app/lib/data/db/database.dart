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

  // Offline state.
  TextColumn get localPath => text().nullable()();
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
  int get schemaVersion => 1;

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

  Future<void> upsertTrack(LocalTracksCompanion track) =>
      into(localTracks).insertOnConflictUpdate(track);

  Future<void> setDownloadState(String id, DownloadState state,
          {int? downloadedBytes, String? localPath}) =>
      (update(localTracks)..where((t) => t.id.equals(id))).write(
        LocalTracksCompanion(
          downloadState: Value(state),
          downloadedBytes:
              downloadedBytes == null ? const Value.absent() : Value(downloadedBytes),
          localPath: localPath == null ? const Value.absent() : Value(localPath),
        ),
      );

  Future<void> touchLastPlayed(String id) =>
      (update(localTracks)..where((t) => t.id.equals(id))).write(
        LocalTracksCompanion(
            lastPlayedAt: Value(DateTime.now().millisecondsSinceEpoch)),
      );
}

LazyDatabase _open() {
  return LazyDatabase(() async {
    final dir = await getApplicationSupportDirectory();
    final file = File(p.join(dir.path, 'library.sqlite'));
    return NativeDatabase.createInBackground(file);
  });
}
