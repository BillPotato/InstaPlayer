import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/settings.dart';
import '../../providers.dart';
import 'storage_screen.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key, this.firstRun = false});

  final bool firstRun;

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  late final TextEditingController _url;
  late final TextEditingController _key;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final s = ref.read(settingsProvider);
    _url = TextEditingController(text: s.baseUrl);
    _key = TextEditingController(text: s.apiKey);
  }

  @override
  void dispose() {
    _url.dispose();
    _key.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    await ref.read(settingsProvider.notifier).save(
          BackendSettings(baseUrl: _url.text.trim(), apiKey: _key.text.trim()),
        );
    if (!mounted) return;
    setState(() => _saving = false);
    if (widget.firstRun) return; // _Root will swap to HomeShell automatically
    Navigator.of(context).maybePop();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Backend connection')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (widget.firstRun)
            const Padding(
              padding: EdgeInsets.only(bottom: 16),
              child: Text(
                'Connect to your self-hosted music backend to get started.',
                style: TextStyle(fontSize: 16),
              ),
            ),
          TextField(
            controller: _url,
            keyboardType: TextInputType.url,
            decoration: const InputDecoration(
              labelText: 'Backend URL',
              hintText: 'https://music.example.com',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _key,
            obscureText: true,
            decoration: const InputDecoration(
              labelText: 'API key',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _saving ? null : _save,
            child: _saving
                ? const SizedBox(
                    height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Save & connect'),
          ),
          if (!widget.firstRun) ...[
            const Divider(height: 48),
            ListTile(
              leading: const Icon(Icons.sd_storage),
              title: const Text('Storage'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const StorageScreen()),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
