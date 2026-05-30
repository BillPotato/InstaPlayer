import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../providers.dart';
import 'delete_helpers.dart';
import 'playlist_detail_screen.dart';

class PlaylistsScreen extends ConsumerWidget {
  const PlaylistsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final playlists = ref.watch(playlistsProvider);
    return playlists.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('Error: $e')),
      data: (list) {
        if (list.isEmpty) {
          return const Center(
            child: Padding(
              padding: EdgeInsets.all(24),
              child: Text('No playlists yet. Add one from the Add tab.',
                  textAlign: TextAlign.center),
            ),
          );
        }
        return RefreshIndicator(
          onRefresh: () async => ref.read(downloadManagerProvider)?.downloadAllMissing(),
          child: ListView.builder(
            itemCount: list.length,
            itemBuilder: (context, i) {
              final pl = list[i];
              return Dismissible(
                key: ValueKey(pl.id),
                direction: DismissDirection.endToStart,
                background: const DeleteBackground(),
                confirmDismiss: (_) =>
                    confirmDeletePlaylist(context, pl.name),
                onDismissed: (_) =>
                    ref.read(downloadManagerProvider)?.deletePlaylist(pl.id),
                child: ListTile(
                  leading: const Icon(Icons.queue_music),
                  title: Text(pl.name),
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) =>
                          PlaylistDetailScreen(playlistId: pl.id, name: pl.name),
                    ),
                  ),
                ),
              );
            },
          ),
        );
      },
    );
  }
}
