import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/db/database.dart';
import '../../providers.dart';
import 'track_art.dart';

/// A single track row used in the library and playlist views. Tapping it starts
/// playback of [queue] at this track's index; a trailing button manages the
/// offline download.
class TrackTile extends ConsumerWidget {
  const TrackTile({
    super.key,
    required this.track,
    required this.queue,
    required this.index,
  });

  final LocalTrack track;
  final List<LocalTrack> queue;
  final int index;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final currentId = ref.watch(currentMediaItemProvider).asData?.value?.id;
    final isCurrent = currentId == track.id;
    final primary = Theme.of(context).colorScheme.primary;

    return ListTile(
      leading: TrackArt(track: track),
      title: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (isCurrent) ...[
            Icon(Icons.graphic_eq, size: 18, color: primary),
            const SizedBox(width: 4),
          ],
          Flexible(
            child: Text(
              track.title.isEmpty ? 'Unknown title' : track.title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: isCurrent ? TextStyle(color: primary) : null,
            ),
          ),
        ],
      ),
      subtitle: Text(track.artist, maxLines: 1, overflow: TextOverflow.ellipsis),
      trailing: _DownloadButton(track: track),
      // Tapping a track just starts playback; the mini-player bar above the
      // nav bar appears automatically (Spotify-style). Tap that bar to open
      // the full Now Playing screen.
      onTap: () async {
        final controller = ref.read(playControllerProvider);
        if (controller == null) return;
        final messenger = ScaffoldMessenger.of(context);
        try {
          await controller.playAll(queue, index);
        } catch (e) {
          messenger.showSnackBar(SnackBar(content: Text('Could not play: $e')));
        }
      },
    );
  }
}

class _DownloadButton extends ConsumerWidget {
  const _DownloadButton({required this.track});

  final LocalTrack track;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dm = ref.watch(downloadManagerProvider);
    switch (track.downloadState) {
      case DownloadState.downloaded:
        return IconButton(
          icon: const Icon(Icons.download_done, color: Colors.greenAccent),
          tooltip: 'Downloaded — tap to remove',
          onPressed: () => dm?.deleteDownload(track.id),
        );
      case DownloadState.downloading:
      case DownloadState.queued:
        return const SizedBox(
          width: 24,
          height: 24,
          child: Padding(
            padding: EdgeInsets.all(2),
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        );
      case DownloadState.failed:
        return IconButton(
          icon: const Icon(Icons.error_outline, color: Colors.redAccent),
          tooltip: 'Failed — tap to retry',
          onPressed: () => dm?.download(track.id),
        );
      case DownloadState.notDownloaded:
        return IconButton(
          icon: const Icon(Icons.download_outlined),
          tooltip: 'Download for offline',
          onPressed: () => dm?.download(track.id),
        );
    }
  }
}
