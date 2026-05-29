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
      if (event.status == 'completed' && event.completed > 0) {
        _importAndDownload(event.id);
      }
    });
  }

  /// Import the finished job's manifest into the local library, download its
  /// tracks (audio + art) onto this device, then delete the job from the
  /// backend once everything is local (the backend stores nothing permanently).
  Future<void> _importAndDownload(String jobId) async {
    final repo = ref.read(libraryRepoProvider);
    final dm = ref.read(downloadManagerProvider);
    final api = ref.read(apiClientProvider);
    if (repo == null || dm == null || api == null) return;

    await repo.importManifest(jobId);
    final allDownloaded = await dm.downloadForJob(jobId);
    if (allDownloaded) {
      // Everything is on the device — release the backend's temp copy.
      try {
        await api.deleteJob(jobId);
      } catch (_) {
        // If cleanup fails the reaper will collect it later; not fatal.
      }
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
