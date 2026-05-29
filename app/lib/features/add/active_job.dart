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
        // Pull the newly downloaded tracks into the local mirror.
        ref.read(libraryRepoProvider)?.sync();
      }
    });
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
