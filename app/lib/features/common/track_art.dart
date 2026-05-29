import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/db/database.dart';
import '../../providers.dart';

/// Album art for a track. Uses the authenticated backend art endpoint via
/// cached_network_image (which can send our bearer header), with a placeholder.
class TrackArt extends ConsumerWidget {
  const TrackArt({super.key, required this.track, this.size = 48});

  final LocalTrack track;
  final double size;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiClientProvider);
    final placeholder = Container(
      width: size,
      height: size,
      color: Colors.white12,
      child: Icon(Icons.music_note, size: size * 0.5, color: Colors.white38),
    );
    if (!track.hasArt || api == null) {
      return ClipRRect(borderRadius: BorderRadius.circular(6), child: placeholder);
    }
    return ClipRRect(
      borderRadius: BorderRadius.circular(6),
      child: CachedNetworkImage(
        imageUrl: api.artUrl(track.id),
        httpHeaders: api.authHeader,
        width: size,
        height: size,
        fit: BoxFit.cover,
        placeholder: (context, url) => placeholder,
        errorWidget: (context, url, error) => placeholder,
      ),
    );
  }
}
