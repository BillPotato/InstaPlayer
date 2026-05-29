import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../providers.dart';
import 'track_art.dart';

/// Album art looked up by track id (used by the player + mini-player, which
/// only have a MediaItem id to work with).
class TrackArtById extends ConsumerWidget {
  const TrackArtById({super.key, required this.trackId, this.size = 48});

  final String trackId;
  final double size;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final track = ref.watch(trackByIdProvider(trackId)).asData?.value;
    final placeholder = ClipRRect(
      borderRadius: BorderRadius.circular(6),
      child: Container(
        width: size,
        height: size,
        color: Colors.white12,
        child: Icon(Icons.music_note, size: size * 0.5, color: Colors.white38),
      ),
    );
    if (track == null) return placeholder;
    return TrackArt(track: track, size: size);
  }
}
