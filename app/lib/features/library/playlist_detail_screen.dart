import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../providers.dart';
import '../common/track_tile.dart';
import 'delete_helpers.dart';

class PlaylistDetailScreen extends ConsumerWidget {
  const PlaylistDetailScreen({super.key, required this.playlistId, required this.name});

  final String playlistId;
  final String name;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tracks = ref.watch(playlistTracksProvider(playlistId));
    return Scaffold(
      appBar: AppBar(title: Text(name)),
      body: tracks.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Error: $e')),
        data: (list) {
          if (list.isEmpty) {
            return const Center(child: Text('This playlist has no downloaded tracks yet.'));
          }
          return Column(
            children: [
              Padding(
                padding: const EdgeInsets.all(8),
                child: Row(
                  children: [
                    FilledButton.icon(
                      icon: const Icon(Icons.play_arrow),
                      label: const Text('Play'),
                      onPressed: () async {
                        final controller = ref.read(playControllerProvider);
                        if (controller == null) return;
                        final messenger = ScaffoldMessenger.of(context);
                        try {
                          await controller.playAll(list, 0);
                        } catch (e) {
                          messenger.showSnackBar(
                              SnackBar(content: Text('Could not play: $e')));
                        }
                      },
                    ),
                    const SizedBox(width: 8),
                    OutlinedButton.icon(
                      icon: const Icon(Icons.download),
                      label: const Text('Download all'),
                      onPressed: () {
                        final dm = ref.read(downloadManagerProvider);
                        for (final t in list) {
                          dm?.download(t.id);
                        }
                      },
                    ),
                  ],
                ),
              ),
              Expanded(
                child: ListView.builder(
                  itemCount: list.length,
                  itemBuilder: (context, i) {
                    final track = list[i];
                    return Dismissible(
                      key: ValueKey(track.id),
                      direction: DismissDirection.endToStart,
                      background: const DeleteBackground(),
                      confirmDismiss: (_) =>
                          confirmDeleteTrack(context, track.title),
                      onDismissed: (_) =>
                          ref.read(downloadManagerProvider)?.deleteTrack(track.id),
                      child: TrackTile(track: track, queue: list, index: i),
                    );
                  },
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
