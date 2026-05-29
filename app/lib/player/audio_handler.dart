import 'package:audio_service/audio_service.dart';
import 'package:just_audio/just_audio.dart';

/// Bridges just_audio to audio_service so playback survives backgrounding and
/// shows lock-screen / notification controls.
///
/// Each [MediaItem] carries its source in `extras`:
///   - `localPath`: absolute file path when the track is downloaded, else
///   - `url` + `headers`: stream straight from the backend (authenticated).
class MusicAudioHandler extends BaseAudioHandler with QueueHandler, SeekHandler {
  MusicAudioHandler() {
    _player.playbackEventStream.map(_toPlaybackState).pipe(playbackState);
    _player.currentIndexStream.listen((index) {
      final q = queue.value;
      if (index != null && index >= 0 && index < q.length) {
        mediaItem.add(q[index]);
      }
    });
  }

  final AudioPlayer _player = AudioPlayer();

  AudioPlayer get player => _player;

  AudioSource _toSource(MediaItem item) {
    final localPath = item.extras?['localPath'] as String?;
    if (localPath != null && localPath.isNotEmpty) {
      return AudioSource.file(localPath, tag: item);
    }
    final url = item.extras!['url'] as String;
    final headers = (item.extras!['headers'] as Map).cast<String, String>();
    return AudioSource.uri(Uri.parse(url), headers: headers, tag: item);
  }

  /// Replace the queue and start playing at [initialIndex].
  Future<void> setQueueAndPlay(List<MediaItem> items, {int initialIndex = 0}) async {
    queue.add(items);
    if (items.isEmpty) return;
    await _player.setAudioSources(
      items.map(_toSource).toList(),
      initialIndex: initialIndex,
    );
    mediaItem.add(items[initialIndex]);
    await _player.play();
  }

  @override
  Future<void> play() => _player.play();

  @override
  Future<void> pause() => _player.pause();

  @override
  Future<void> seek(Duration position) => _player.seek(position);

  @override
  Future<void> skipToNext() => _player.seekToNext();

  @override
  Future<void> skipToPrevious() => _player.seekToPrevious();

  @override
  Future<void> skipToQueueItem(int index) => _player.seek(Duration.zero, index: index);

  @override
  Future<void> stop() async {
    await _player.stop();
    await super.stop();
  }

  PlaybackState _toPlaybackState(PlaybackEvent event) {
    final playing = _player.playing;
    return PlaybackState(
      controls: [
        MediaControl.skipToPrevious,
        if (playing) MediaControl.pause else MediaControl.play,
        MediaControl.skipToNext,
      ],
      systemActions: const {MediaAction.seek},
      androidCompactActionIndices: const [0, 1, 2],
      processingState: switch (_player.processingState) {
        ProcessingState.idle => AudioProcessingState.idle,
        ProcessingState.loading => AudioProcessingState.loading,
        ProcessingState.buffering => AudioProcessingState.buffering,
        ProcessingState.ready => AudioProcessingState.ready,
        ProcessingState.completed => AudioProcessingState.completed,
      },
      playing: playing,
      updatePosition: _player.position,
      bufferedPosition: _player.bufferedPosition,
      speed: _player.speed,
      queueIndex: event.currentIndex,
    );
  }
}
