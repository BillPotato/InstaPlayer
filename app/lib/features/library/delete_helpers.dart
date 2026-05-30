import 'package:flutter/material.dart';

/// Red background shown behind a dismissing list tile.
class DeleteBackground extends StatelessWidget {
  const DeleteBackground({super.key});

  @override
  Widget build(BuildContext context) => Container(
        color: Colors.red,
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.symmetric(horizontal: 20),
        child: const Icon(Icons.delete, color: Colors.white),
      );
}

/// Shows a confirmation dialog before allowing a track to be deleted.
/// Returns true to confirm, false/null to cancel (tile snaps back).
Future<bool?> confirmDeleteTrack(BuildContext context, String title) =>
    showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Delete song?'),
        content: Text('"$title" will be removed from your device.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text('Delete', style: TextStyle(color: Colors.red[400])),
          ),
        ],
      ),
    );

/// Shows a confirmation dialog before allowing a playlist to be deleted.
Future<bool?> confirmDeletePlaylist(BuildContext context, String name) =>
    showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Delete playlist?'),
        content: Text(
            '"$name" and all its songs will be removed from your device.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text('Delete', style: TextStyle(color: Colors.red[400])),
          ),
        ],
      ),
    );
