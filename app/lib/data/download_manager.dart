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

  bool _batchRunning = false;

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

      // Album art is best-effort: a missing/failed art fetch doesn't fail the track.
      final artPath = track.hasArt ? await _downloadArt(trackId, jobId, n) : null;

      await _db.setDownloadState(trackId, DownloadState.downloaded,
          downloadedBytes: received, localPath: finalFile.path, localArtPath: artPath);
    } catch (e) {
      await sink.close();
      await _db.setDownloadState(trackId, DownloadState.failed);
      rethrow;
    }
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

  /// Pull every track that isn't on this device yet, a few at a time. Safe to
  /// call repeatedly — it no-ops while a batch is already running.
  Future<void> downloadAllMissing({int concurrency = 3}) async {
    if (_batchRunning) return;
    _batchRunning = true;
    try {
      await _runBatch(await _db.tracksNeedingDownload(), concurrency: concurrency);
    } finally {
      _batchRunning = false;
    }
  }

  /// Download all of one job's tracks. Returns true if every track ended up on
  /// the device (so the caller can safely DELETE the job from the backend).
  Future<bool> downloadForJob(String jobId, {int concurrency = 3}) async {
    await _runBatch(await _db.tracksForJobNotDownloaded(jobId), concurrency: concurrency);
    final remaining = await _db.tracksForJobNotDownloaded(jobId);
    return remaining.isEmpty;
  }

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
