import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'features/add/add_screen.dart';
import 'features/library/library_screen.dart';
import 'features/library/playlists_screen.dart';
import 'features/player/mini_player.dart';
import 'features/settings/settings_screen.dart';
import 'providers.dart';

class MusicApp extends ConsumerWidget {
  const MusicApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MaterialApp(
      title: 'Music',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1DB954),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const _Root(),
    );
  }
}

/// Gate the app behind backend configuration, then show the tabbed shell.
class _Root extends ConsumerWidget {
  const _Root();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final configured = ref.watch(settingsProvider).isConfigured;
    if (!configured) return const SettingsScreen(firstRun: true);
    return const HomeShell();
  }
}

class HomeShell extends ConsumerStatefulWidget {
  const HomeShell({super.key});

  @override
  ConsumerState<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends ConsumerState<HomeShell> {
  int _index = 0;

  static const _tabs = [PlaylistsScreen(), LibraryScreen(), AddScreen()];

  @override
  void initState() {
    super.initState();
    // Best-effort metadata sync on launch; ignored when offline.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(libraryRepoProvider)?.sync().ignore();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Music'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const SettingsScreen()),
            ),
          ),
        ],
      ),
      body: _tabs[_index],
      bottomNavigationBar: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const MiniPlayer(),
          NavigationBar(
            selectedIndex: _index,
            onDestinationSelected: (i) => setState(() => _index = i),
            destinations: const [
              NavigationDestination(icon: Icon(Icons.queue_music), label: 'Playlists'),
              NavigationDestination(icon: Icon(Icons.library_music), label: 'Songs'),
              NavigationDestination(icon: Icon(Icons.add_circle_outline), label: 'Add'),
            ],
          ),
        ],
      ),
    );
  }
}
