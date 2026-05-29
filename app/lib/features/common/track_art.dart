import 'dart:io';

import 'package:flutter/material.dart';

import '../../data/db/database.dart';

/// Album art for a track, loaded from the local art file downloaded alongside
/// the audio (the backend keeps no copy). Falls back to a placeholder.
class TrackArt extends StatelessWidget {
  const TrackArt({super.key, required this.track, this.size = 48});

  final LocalTrack track;
  final double size;

  @override
  Widget build(BuildContext context) {
    final path = track.localArtPath;
    final placeholder = Container(
      width: size,
      height: size,
      color: Colors.white12,
      child: Icon(Icons.music_note, size: size * 0.5, color: Colors.white38),
    );
    final hasFile = path != null && path.isNotEmpty && File(path).existsSync();
    return ClipRRect(
      borderRadius: BorderRadius.circular(6),
      child: hasFile
          ? Image.file(
              File(path),
              width: size,
              height: size,
              fit: BoxFit.cover,
              errorBuilder: (_, __, ___) => placeholder,
            )
          : placeholder,
    );
  }
}
