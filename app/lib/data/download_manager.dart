import 'dart:io';

import 'package:dio/dio.dart';
import 'package:drift/drift.dart' show Value;
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import '../core/api_client.dart';
import 'db/database.dart';

/// Downloads FLAC files for offline playback, resuming via HTTP Range so an
/// interrupted transfer continues from the byte it stopped at.
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

  Future<File> fileFor(String trackId) async =>
      File(p.join((await _musicDir()).path, '$trackId.flac'));

  /// Returns true when the track's FLAC is fully present on this device.
  Future<bool> isDownloaded(String trackId) async {
    final track = await _db.trackById(trackId);
    if (track?.localPath == null) return false;
    return File(track!.localPath!).existsSync();
  }

  /// Download a single track, resuming if a partial file exists.
  Future<void> download(String trackId, {void Function(int received, int total)? onProgress}) async {
    final partFile = File('${(await fileFor(trackId)).path}.part');
    final finalFile = await fileFor(trackId);
    final existing = partFile.existsSync() ? partFile.lengthSync() : 0;

    await _db.setDownloadState(trackId, DownloadState.downloading,
        downloadedBytes: existing);

    final sink = partFile.openWrite(mode: FileMode.append);
    try {
      final response = await _api.raw.get<ResponseBody>(
        '/tracks/$trackId/file',
        options: Options(
          responseType: ResponseType.stream,
          headers: {if (existing > 0) 'Range': 'bytes=$existing-'},
          // 206 (partial) and 200 (full) are both acceptable.
          validateStatus: (s) => s != null && s < 400,
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
      await _db.setDownloadState(trackId, DownloadState.downloaded,
          downloadedBytes: received, localPath: finalFile.path);
    } catch (e) {
      await sink.close();
      await _db.setDownloadState(trackId, DownloadState.failed);
      rethrow;
    }
  }

  Future<void> deleteDownload(String trackId) async {
    final file = await fileFor(trackId);
    if (file.existsSync()) file.deleteSync();
    final part = File('${file.path}.part');
    if (part.existsSync()) part.deleteSync();
    await _db.setDownloadState(trackId, DownloadState.notDownloaded,
        downloadedBytes: 0, localPath: '');
    // Clear localPath explicitly (empty string above signals "none").
    await (_db.update(_db.localTracks)..where((t) => t.id.equals(trackId)))
        .write(const LocalTracksCompanion(localPath: Value(null)));
  }

  /// Pull every track that isn't on this device yet, [concurrency] at a time,
  /// so the whole library becomes available offline. Safe to call repeatedly —
  /// it no-ops while a batch is already running and skips already-downloaded
  /// tracks. Individual failures are left in the `failed` state for retry and
  /// don't abort the batch.
  Future<void> downloadAllMissing({int concurrency = 3}) async {
    if (_batchRunning) return;
    _batchRunning = true;
    try {
      final pending = await _db.tracksNeedingDownload();
      if (pending.isEmpty) return;
      // Mark queued up front so every row shows a spinner immediately.
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
    } finally {
      _batchRunning = false;
    }
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
