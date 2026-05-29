import 'package:audio_service/audio_service.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/api_client.dart';
import 'core/settings.dart';
import 'data/db/database.dart';
import 'data/download_manager.dart';
import 'data/library_repository.dart';
import 'player/audio_handler.dart';
import 'player/play_controller.dart';

final settingsRepoProvider = Provider((ref) => SettingsRepository());

/// Mutable backend connection settings, loaded once at startup.
class SettingsNotifier extends Notifier<BackendSettings> {
  @override
  BackendSettings build() => BackendSettings.empty;

  Future<void> load() async {
    state = await ref.read(settingsRepoProvider).load();
  }

  Future<void> save(BackendSettings settings) async {
    await ref.read(settingsRepoProvider).save(settings);
    state = settings;
  }
}

final settingsProvider =
    NotifierProvider<SettingsNotifier, BackendSettings>(SettingsNotifier.new);

final apiClientProvider = Provider<ApiClient?>((ref) {
  final s = ref.watch(settingsProvider);
  return s.isConfigured ? ApiClient(s) : null;
});

final dbProvider = Provider<AppDatabase>((ref) {
  final db = AppDatabase();
  ref.onDispose(db.close);
  return db;
});

final downloadManagerProvider = Provider<DownloadManager?>((ref) {
  final api = ref.watch(apiClientProvider);
  if (api == null) return null;
  return DownloadManager(api, ref.watch(dbProvider));
});

final libraryRepoProvider = Provider<LibraryRepository?>((ref) {
  final api = ref.watch(apiClientProvider);
  if (api == null) return null;
  return LibraryRepository(api, ref.watch(dbProvider));
});

final tracksProvider = StreamProvider<List<LocalTrack>>(
    (ref) => ref.watch(dbProvider).watchAllTracks());

final playlistsProvider = StreamProvider<List<LocalPlaylist>>(
    (ref) => ref.watch(dbProvider).watchPlaylists());

final playlistTracksProvider =
    FutureProvider.family<List<LocalTrack>, String>((ref, playlistId) {
  // Re-fetch when the mirror changes.
  ref.watch(tracksProvider);
  return ref.watch(dbProvider).playlistTracks(playlistId);
});

/// Set via ProviderScope override in main() after AudioService.init().
final audioHandlerProvider = Provider<MusicAudioHandler>(
    (ref) => throw UnimplementedError('audioHandlerProvider must be overridden'));

/// Convenience: the underlying AudioService handler as a BaseAudioHandler.
final audioServiceProvider = Provider<AudioHandler>(
    (ref) => ref.watch(audioHandlerProvider));

final playControllerProvider = Provider<PlayController?>((ref) {
  final api = ref.watch(apiClientProvider);
  if (api == null) return null;
  return PlayController(
    ref.watch(audioHandlerProvider),
    api,
    ref.watch(dbProvider),
  );
});

/// The MediaItem currently loaded in the player (null when nothing is playing).
final currentMediaItemProvider = StreamProvider<MediaItem?>(
    (ref) => ref.watch(audioHandlerProvider).mediaItem);

/// Look up a local track by id; re-emits when the mirror changes.
final trackByIdProvider = FutureProvider.family<LocalTrack?, String>((ref, id) {
  ref.watch(tracksProvider);
  return ref.watch(dbProvider).trackById(id);
});
