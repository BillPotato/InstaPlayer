import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../providers.dart';

final _usedBytesProvider = FutureProvider.autoDispose<int>((ref) async {
  // Recompute when the library mirror changes.
  ref.watch(tracksProvider);
  return await ref.watch(downloadManagerProvider)?.usedBytes() ?? 0;
});

String _human(int bytes) {
  if (bytes < 1024) return '$bytes B';
  const units = ['KB', 'MB', 'GB'];
  var size = bytes / 1024;
  var unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit++;
  }
  return '${size.toStringAsFixed(1)} ${units[unit]}';
}

class StorageScreen extends ConsumerWidget {
  const StorageScreen({super.key});

  // A sensible default offline cap; could be made user-configurable.
  static const int defaultCapBytes = 4 * 1024 * 1024 * 1024; // 4 GB

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final used = ref.watch(_usedBytesProvider);
    final dm = ref.watch(downloadManagerProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Storage')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ListTile(
            leading: const Icon(Icons.sd_storage),
            title: const Text('Downloaded music'),
            subtitle: used.when(
              loading: () => const Text('Calculating…'),
              error: (e, _) => Text('Error: $e'),
              data: (b) => Text('${_human(b)} used (cap ${_human(defaultCapBytes)})'),
            ),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            icon: const Icon(Icons.cleaning_services),
            label: const Text('Free space to fit cap'),
            onPressed: dm == null
                ? null
                : () async {
                    final freed = await dm.enforceCap(defaultCapBytes);
                    ref.invalidate(_usedBytesProvider);
                    if (context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(content: Text('Freed ${_human(freed)}')),
                      );
                    }
                  },
          ),
        ],
      ),
    );
  }
}
