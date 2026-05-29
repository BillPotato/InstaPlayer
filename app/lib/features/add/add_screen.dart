import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../data/models.dart';
import 'active_job.dart';

class AddScreen extends ConsumerStatefulWidget {
  const AddScreen({super.key});

  @override
  ConsumerState<AddScreen> createState() => _AddScreenState();
}

class _AddScreenState extends ConsumerState<AddScreen> {
  final _url = TextEditingController();
  String? _message;
  bool _submitting = false;

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final text = _url.text.trim();
    if (text.isEmpty) return;
    setState(() {
      _submitting = true;
      _message = null;
    });
    try {
      await ref.read(activeJobProvider.notifier).submit(text);
    } catch (e) {
      setState(() => _message = 'Failed to start: $e');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final job = ref.watch(activeJobProvider);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text('Paste a Spotify playlist, album, or track URL.',
            style: TextStyle(fontSize: 16)),
        const SizedBox(height: 12),
        TextField(
          controller: _url,
          decoration: const InputDecoration(
            labelText: 'Spotify URL',
            hintText: 'https://open.spotify.com/playlist/...',
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: _submitting ? null : _submit,
          icon: const Icon(Icons.cloud_download),
          label: const Text('Fetch & download'),
        ),
        if (_message != null) ...[
          const SizedBox(height: 16),
          Text(_message!, style: const TextStyle(color: Colors.redAccent)),
        ],
        if (job != null) ...[
          const SizedBox(height: 24),
          _JobProgress(job: job),
          if (job.isTerminal) ...[
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () =>
                    ref.read(activeJobProvider.notifier).clear(),
                child: const Text('Dismiss'),
              ),
            ),
          ],
        ],
      ],
    );
  }
}

class _JobProgress extends StatelessWidget {
  const _JobProgress({required this.job});

  final JobDto job;

  ({String label, IconData icon, Color color}) _status() {
    if (job.status == 'failed') {
      return (
        label: 'Failed: ${job.error ?? 'unknown error'}',
        icon: Icons.error,
        color: Colors.redAccent,
      );
    }
    if (job.status == 'completed') {
      if (job.completed == 0) {
        return (
          label: job.error ?? 'No tracks could be downloaded.',
          icon: Icons.report_problem,
          color: Colors.orangeAccent,
        );
      }
      if (job.total > 0 && job.completed < job.total) {
        return (
          label: 'Downloaded ${job.completed} of ${job.total} — '
              'some tracks were unavailable.',
          icon: Icons.warning_amber,
          color: Colors.orangeAccent,
        );
      }
      return (
        label: 'Added ${job.completed} tracks',
        icon: Icons.check_circle,
        color: Colors.greenAccent,
      );
    }
    // running / queued
    final count = job.total > 0 ? '${job.completed} / ${job.total}' : '${job.completed}';
    return (
      label: job.status == 'running' ? 'Downloading… $count' : 'Queued…',
      icon: job.status == 'running' ? Icons.downloading : Icons.schedule,
      color: Colors.blueAccent,
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = _status();
    // Determinate when we know the total, otherwise indeterminate.
    final double? value = (!job.isTerminal && job.total > 0)
        ? (job.completed / job.total).clamp(0.0, 1.0).toDouble()
        : null;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(s.icon, color: s.color),
                const SizedBox(width: 8),
                Expanded(child: Text(s.label)),
              ],
            ),
            if (!job.isTerminal) ...[
              const SizedBox(height: 12),
              LinearProgressIndicator(value: value),
              if (job.current != null) ...[
                const SizedBox(height: 8),
                Text(
                  job.current!,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }
}
