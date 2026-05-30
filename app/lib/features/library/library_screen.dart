import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../providers.dart';
import '../common/track_tile.dart';
import 'delete_helpers.dart';

/// Flat list of every track in the library (the "Songs" tab).
class LibraryScreen extends ConsumerWidget {
  const LibraryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tracks = ref.watch(tracksProvider);
    return tracks.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('Error: $e')),
      data: (list) {
        if (list.isEmpty) {
          return const Center(
            child: Padding(
              padding: EdgeInsets.all(24),
              child: Text('No songs yet. Add a Spotify playlist from the Add tab.',
                  textAlign: TextAlign.center),
            ),
          );
        }
        return RefreshIndicator(
          onRefresh: () async => ref.read(downloadManagerProvider)?.downloadAllMissing(),
          child: ListView.builder(
            itemCount: list.length,
            itemBuilder: (context, i) {
              final track = list[i];
              return Dismissible(
                key: ValueKey(track.id),
                direction: DismissDirection.endToStart,
                background: const DeleteBackground(),
                confirmDismiss: (_) => confirmDeleteTrack(context, track.title),
                onDismissed: (_) =>
                    ref.read(downloadManagerProvider)?.deleteTrack(track.id),
                child: TrackTile(track: track, queue: list, index: i),
              );
            },
          ),
        );
      },
    );
  }
}
