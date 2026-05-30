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

  @override
  JobDto? build() {
    ref.onDispose(() {
      _sub?.cancel();
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
    _sub = tracker.updates.listen((event) {
      state = event;
      // Import on every progress tick (not just completion) so each finished
      // track shows up in the library as soon as the backend has it, and starts
      // downloading to the device — no waiting for the whole playlist.
      if (event.status == 'running' || event.status == 'completed') {
        _onProgress(event.id, terminal: event.status == 'completed');
      }
    });
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
    _tracker?.dispose();
    _tracker = null;
    _sub = null;
    state = null;
  }
}

final activeJobProvider =
    NotifierProvider<ActiveJobNotifier, JobDto?>(ActiveJobNotifier.new);
