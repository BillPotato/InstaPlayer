import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/models.dart';
import '../../providers.dart';
import 'job_tracker.dart';

/// App-scoped owner of the currently-tracked download job. Lives for the app's
/// lifetime (not tied to the Add screen), so progress survives tab switches and
/// the completion-triggered library sync always runs.
class ActiveJobNotifier extends Notifier<JobDto?> {
  JobTracker? _tracker;
  StreamSubscription<JobDto>? _sub;
  StreamSubscription<int>? _fileReadySub;

  @override
  JobDto? build() {
    ref.onDispose(() {
      _sub?.cancel();
      _fileReadySub?.cancel();
      _tracker?.dispose();
    });
    return null;
  }

  /// Create a job on the backend and start tracking it. Throws if the backend
  /// is not configured or the request fails (caller shows the error).
  Future<void> submit(String spotifyUrl) async {
    final api = ref.read(apiClientProvider);
    if (api == null) {
      throw StateError('Backend is not configured');
    }
    // Tear down any previous job tracker.
    await _sub?.cancel();
    _tracker?.dispose();
    _tracker = null;
    state = null;

    final job = await api.createJob(spotifyUrl);
    state = job;

    final tracker = JobTracker(api, job.id)..start();
    _tracker = tracker;

    // Fast path: a file_ready event fires the moment a specific track becomes
    // fetchable on the backend. Import the manifest (so the track is in drift)
    // then kick off the device download immediately — no polling delay.
    _fileReadySub = tracker.fileReady.listen((_) => _onFileReady(job.id));

    // Slow path / fallback: status ticks cover the case where the WebSocket
    // dropped and we're polling REST (which has no file_ready events).
    _sub = tracker.updates.listen((event) {
      state = event;
      if (event.status == 'running' || event.status == 'completed') {
        _onProgress(event.id, terminal: event.status == 'completed');
      }
    });
  }

  Future<void> _onFileReady(String jobId) async {
    await _importAvailable(jobId);
    ref.read(downloadManagerProvider)?.downloadAllMissing();
  }

  // Serialise importing so overlapping progress events don't race; if events
  // arrive while an import is running, do one more pass afterwards.
  bool _importing = false;
  bool _importAgain = false;

  Future<void> _onProgress(String jobId, {required bool terminal}) async {
    await _importAvailable(jobId);
    // Keep the device download draining (chained — safe to call repeatedly).
    ref.read(downloadManagerProvider)?.downloadAllMissing();

    if (terminal) {
      final dm = ref.read(downloadManagerProvider);
      final api = ref.read(apiClientProvider);
      if (dm == null || api == null) return;
      // Wait for a full drain that runs after the final import, then release
      // the backend's temp copy if everything made it onto the device.
      await dm.downloadAllMissing();
      if (await dm.isJobFullyDownloaded(jobId)) {
        try {
          await api.deleteJob(jobId);
        } catch (_) {
          // If cleanup fails the reaper collects it later; not fatal.
        }
      }
    }
  }

  /// Import whatever tracks are currently in the job's manifest into drift.
  /// Idempotent (upserts); a not-ready/404 manifest is ignored.
  Future<void> _importAvailable(String jobId) async {
    if (_importing) {
      _importAgain = true;
      return;
    }
    _importing = true;
    try {
      do {
        _importAgain = false;
        final repo = ref.read(libraryRepoProvider);
        if (repo == null) return;
        try {
          await repo.importManifest(jobId);
        } catch (_) {
          // Manifest not ready yet (no tracks finished) or transient error.
        }
      } while (_importAgain);
    } finally {
      _importing = false;
    }
  }

  /// Dismiss the current job card.
  void clear() {
    _sub?.cancel();
    _fileReadySub?.cancel();
    _tracker?.dispose();
    _tracker = null;
    _sub = null;
    _fileReadySub = null;
    state = null;
  }
}

final activeJobProvider =
    NotifierProvider<ActiveJobNotifier, JobDto?>(ActiveJobNotifier.new);
