import 'dart:io';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' show Value;
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import '../core/api_client.dart';
import 'db/database.dart';

/// Downloads FLAC files (+ album art) from a backend job onto this device for
/// offline playback. Audio transfers resume via HTTP Range. Once a track is
/// downloaded it plays entirely from the local file — the backend keeps no copy.
class DownloadManager {
  DownloadManager(this._api, this._db);

  final ApiClient _api;
  final AppDatabase _db;

  // Drains run one-after-another. Chaining means a call made while a drain is
  // in flight still resolves only after a drain that starts *after* it, so the
  // terminal "is everything downloaded?" check is reliable.
  Future<void> _drainChain = Future<void>.value();

  Future<Directory> _musicDir() async {
    final base = await getApplicationSupportDirectory();
    final dir = Directory(p.join(base.path, 'music'));
    if (!dir.existsSync()) dir.createSync(recursive: true);
    return dir;
  }

  // Track ids can contain ':' (e.g. "isrc:US..."), illegal in filenames.
  String _safeName(String trackId) => trackId.replaceAll(RegExp(r'[^A-Za-z0-9]'), '_');

  Future<File> fileFor(String trackId) async =>
      File(p.join((await _musicDir()).path, '${_safeName(trackId)}.flac'));

  Future<File> _artFileFor(String trackId) async =>
      File(p.join((await _musicDir()).path, '${_safeName(trackId)}.art'));

  /// Returns true when the track's FLAC is fully present on this device.
  Future<bool> isDownloaded(String trackId) async {
    final track = await _db.trackById(trackId);
    if (track?.localPath == null) return false;
    return File(track!.localPath!).existsSync();
  }

  /// Download a single track's audio (+ art) from its backend job, resuming the
  /// audio if a partial file exists.
  Future<void> download(String trackId, {void Function(int received, int total)? onProgress}) async {
    final track = await _db.trackById(trackId);
    if (track == null) throw StateError('Unknown track $trackId');
    final jobId = track.remoteJobId;
    final n = track.remoteIndex;
    if (jobId == null || n == null) {
      await _db.setDownloadState(trackId, DownloadState.failed);
      throw StateError('Track has no remote source — re-add the playlist');
    }

    final finalFile = await fileFor(trackId);

    // Fast path: FLAC already on device (e.g. from a previous session whose DB
    // row was reset to notDownloaded). Skip the transfer; just ensure art exists.
    if (finalFile.existsSync()) {
      final artPath = await _ensureArt(track, jobId, n);
      await _db.setDownloadState(trackId, DownloadState.downloaded,
          downloadedBytes: finalFile.lengthSync(),
          localPath: finalFile.path,
          localArtPath: artPath);
      return;
    }

    final partFile = File('${finalFile.path}.part');
    final existing = partFile.existsSync() ? partFile.lengthSync() : 0;

    await _db.setDownloadState(trackId, DownloadState.downloading,
        downloadedBytes: existing);

    final sink = partFile.openWrite(mode: FileMode.append);
    try {
      final response = await _api.raw.get<ResponseBody>(
        '/jobs/$jobId/files/$n',
        options: Options(
          responseType: ResponseType.stream,
          headers: {if (existing > 0) 'Range': 'bytes=$existing-'},
          validateStatus: (s) => s != null && s < 400, // 200 or 206
        ),
      );

      final totalHeader = response.data!.contentLength;
      final total = (totalHeader > 0 ? totalHeader + existing : 0);
      var received = existing;

      await for (final chunk in response.data!.stream) {
        sink.add(chunk);
        received += chunk.length;
        onProgress?.call(received, total);
      }
      await sink.flush();
      await sink.close();
      await partFile.rename(finalFile.path);

      final artPath = await _ensureArt(track, jobId, n);

      await _db.setDownloadState(trackId, DownloadState.downloaded,
          downloadedBytes: received, localPath: finalFile.path, localArtPath: artPath);
    } catch (e) {
      await sink.close();
      await _db.setDownloadState(trackId, DownloadState.failed);
      rethrow;
    }
  }

  /// Returns a local art path for [track]: reuses the file if it already exists
  /// on this device (e.g. from a previous session), otherwise fetches from the
  /// backend. Returns null if the track has no art or the fetch fails.
  Future<String?> _ensureArt(LocalTrack track, String jobId, int n) async {
    if (!track.hasArt) return null;
    final artFile = await _artFileFor(track.id);
    if (artFile.existsSync()) return artFile.path;
    return _downloadArt(track.id, jobId, n);
  }

  Future<String?> _downloadArt(String trackId, String jobId, int n) async {
    try {
      final r = await _api.raw.get<List<int>>(
        '/jobs/$jobId/art/$n',
        options: Options(
          responseType: ResponseType.bytes,
          validateStatus: (s) => s != null && s < 400,
        ),
      );
      final bytes = r.data;
      if (bytes == null || bytes.isEmpty) return null;
      final artFile = await _artFileFor(trackId);
      await artFile.writeAsBytes(bytes);
      return artFile.path;
    } catch (_) {
      return null;
    }
  }

  Future<void> deleteDownload(String trackId) async {
    final file = await fileFor(trackId);
    if (file.existsSync()) file.deleteSync();
    final part = File('${file.path}.part');
    if (part.existsSync()) part.deleteSync();
    final art = await _artFileFor(trackId);
    if (art.existsSync()) art.deleteSync();
    await _db.setDownloadState(trackId, DownloadState.notDownloaded, downloadedBytes: 0);
    // Clear the path columns explicitly.
    await (_db.update(_db.localTracks)..where((t) => t.id.equals(trackId)))
        .write(const LocalTracksCompanion(
            localPath: Value(null), localArtPath: Value(null)));
  }

  /// Permanently remove a track: deletes its files then its DB row + join rows.
  Future<void> deleteTrack(String trackId) async {
    await deleteDownload(trackId);
    await _db.deleteTrackRow(trackId);
  }

  /// Permanently remove a playlist and all tracks that belong only to it.
  /// Tracks shared with other playlists are left untouched.
  Future<void> deletePlaylist(String playlistId) async {
    final orphans = await _db.tracksOnlyInPlaylist(playlistId);
    for (final track in orphans) {
      await deleteDownload(track.id);
      await _db.deleteTrackRow(track.id);
    }
    await _db.deletePlaylistRow(playlistId);
  }

  Future<void> _runBatch(List<LocalTrack> pending, {int concurrency = 3}) async {
    if (pending.isEmpty) return;
    for (final t in pending) {
      await _db.setDownloadState(t.id, DownloadState.queued);
    }
    final queue = List<LocalTrack>.of(pending);
    Future<void> worker() async {
      while (queue.isNotEmpty) {
        final t = queue.removeAt(0); // sync check+remove → no race
        try {
          await download(t.id);
        } catch (_) {
          // download() already set the row to failed; keep going.
        }
      }
    }
    await Future.wait([for (var i = 0; i < concurrency; i++) worker()]);
  }

  // Keep downloading until nothing is pending, re-querying each round so tracks
  // imported mid-drain (as more arrive from the backend) are picked up too.
  // Tracks that fail in this pass are excluded from subsequent iterations so a
  // 404 (deleted job, expired file) doesn't spin forever — they stay in
  // 'failed' and are retried only on the next downloadAllMissing() call.
  Future<void> _drainOnce({int concurrency = 3}) async {
    final attempted = <String>{};
    while (true) {
      final all = await _db.tracksNeedingDownload();
      final pending = all.where((t) => !attempted.contains(t.id)).toList();
      if (pending.isEmpty) return;
      for (final t in pending) { attempted.add(t.id); }
      await _runBatch(pending, concurrency: concurrency);
    }
  }

  /// Download every track that isn't on this device yet. Calls are serialised
  /// onto a chain so they never overlap and the returned future resolves only
  /// after a full drain that began at/after this call.
  Future<void> downloadAllMissing({int concurrency = 3}) {
    final next = _drainChain.then((_) => _drainOnce(concurrency: concurrency));
    // Swallow errors on the chain so one failure can't poison later drains.
    _drainChain = next.catchError((_) {});
    return next;
  }

  /// True when all of a job's tracks are downloaded onto this device — i.e. the
  /// backend's temp copy can be safely deleted.
  Future<bool> isJobFullyDownloaded(String jobId) async =>
      (await _db.tracksForJobNotDownloaded(jobId)).isEmpty;

  /// Total bytes used by downloaded FLACs on this device.
  Future<int> usedBytes() async {
    final dir = await _musicDir();
    var total = 0;
    for (final f in dir.listSync()) {
      if (f is File) total += f.lengthSync();
    }
    return total;
  }

  /// Evict least-recently-played, unpinned downloads until usage fits [capBytes].
  Future<int> enforceCap(int capBytes) async {
    var used = await usedBytes();
    if (used <= capBytes) return 0;
    var freed = 0;
    for (final track in await _db.downloadedLru()) {
      if (used <= capBytes) break;
      final size = track.fileSize;
      await deleteDownload(track.id);
      used -= size;
      freed += size;
    }
    return freed;
  }
}
