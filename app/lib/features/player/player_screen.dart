import 'package:audio_service/audio_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../providers.dart';
import '../common/track_art_by_id.dart';

class PlayerScreen extends ConsumerWidget {
  const PlayerScreen({super.key});

  String _fmt(Duration d) {
    final m = d.inMinutes.remainder(60).toString();
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final handler = ref.watch(audioHandlerProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Now playing')),
      body: StreamBuilder<MediaItem?>(
        stream: handler.mediaItem,
        builder: (context, snap) {
          final item = snap.data;
          if (item == null) {
            return const Center(child: Text('Nothing playing'));
          }
          return Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              children: [
                const Spacer(),
                TrackArtById(trackId: item.id, size: 220),
                const SizedBox(height: 24),
                Text(item.title,
                    style: Theme.of(context).textTheme.titleLarge,
                    textAlign: TextAlign.center),
                Text(item.artist ?? '',
                    style: Theme.of(context).textTheme.bodyMedium),
                const SizedBox(height: 16),
                _SeekBar(fmt: _fmt),
                const _Controls(),
                const SizedBox(height: 8),
                TextButton.icon(
                  icon: const Icon(Icons.lyrics_outlined),
                  label: const Text('Lyrics'),
                  onPressed: () => _showLyrics(context, ref, item.id),
                ),
                const Spacer(),
              ],
            ),
          );
        },
      ),
    );
  }

  void _showLyrics(BuildContext context, WidgetRef ref, String trackId) {
    final db = ref.read(dbProvider);
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => FutureBuilder<String?>(
        future: db.trackById(trackId).then((t) => t?.lyrics),
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const SizedBox(
                height: 200, child: Center(child: CircularProgressIndicator()));
          }
          final lyrics = snap.data;
          return SizedBox(
            height: MediaQuery.of(context).size.height * 0.6,
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: Text(lyrics ?? 'No lyrics available.',
                  style: const TextStyle(height: 1.5)),
            ),
          );
        },
      ),
    );
  }
}

class _SeekBar extends ConsumerWidget {
  const _SeekBar({required this.fmt});

  final String Function(Duration) fmt;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final player = ref.watch(audioHandlerProvider).player;
    return StreamBuilder<Duration>(
      stream: player.positionStream,
      builder: (context, posSnap) {
        final position = posSnap.data ?? Duration.zero;
        final total = player.duration ?? Duration.zero;
        final max = total.inMilliseconds.toDouble();
        final value = position.inMilliseconds.clamp(0, max == 0 ? 0 : max).toDouble();
        return Column(
          children: [
            Slider(
              value: max == 0 ? 0 : value,
              max: max == 0 ? 1 : max,
              onChanged: (v) => player.seek(Duration(milliseconds: v.round())),
            ),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [Text(fmt(position)), Text(fmt(total))],
            ),
          ],
        );
      },
    );
  }
}

class _Controls extends ConsumerWidget {
  const _Controls();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final handler = ref.watch(audioHandlerProvider);
    return StreamBuilder<PlaybackState>(
      stream: handler.playbackState,
      builder: (context, snap) {
        final playing = snap.data?.playing ?? false;
        return Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            IconButton(
              iconSize: 40,
              icon: const Icon(Icons.skip_previous),
              onPressed: handler.skipToPrevious,
            ),
            IconButton(
              iconSize: 64,
              icon: Icon(playing ? Icons.pause_circle : Icons.play_circle),
              onPressed: () => playing ? handler.pause() : handler.play(),
            ),
            IconButton(
              iconSize: 40,
              icon: const Icon(Icons.skip_next),
              onPressed: handler.skipToNext,
            ),
          ],
        );
      },
    );
  }
}
