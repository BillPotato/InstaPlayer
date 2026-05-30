import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import '../../core/api_client.dart';
import '../../data/models.dart';

/// Tracks a backend job's progress reliably: it streams events over the
/// WebSocket, auto-reconnects with backoff if the socket drops, and falls back
/// to polling `GET /jobs/{id}` if the socket can't be re-established — so the
/// UI keeps updating even through network blips, until the job is terminal.
class JobTracker {
  JobTracker(this._api, this.jobId);

  final ApiClient _api;
  final String jobId;

  final _controller = StreamController<JobDto>.broadcast();
  final _fileReadyController = StreamController<int>.broadcast();
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  Timer? _reconnectTimer;
  Timer? _pollTimer;
  int _reconnectAttempts = 0;
  bool _terminal = false;
  bool _disposed = false;

  /// Job status updates (queued / running / completed / failed).
  Stream<JobDto> get updates => _controller.stream;

  /// Fires with the track index ``n`` the moment the backend marks it fetchable.
  /// Use this to start downloading a track immediately instead of waiting for
  /// the next status poll.
  Stream<int> get fileReady => _fileReadyController.stream;

  void start() => _connectWs();

  void _connectWs() {
    if (_disposed || _terminal) return;
    try {
      final channel = WebSocketChannel.connect(_api.jobEventsUri(jobId));
      _channel = channel;
      _sub = channel.stream.listen(
        (data) {
          _reconnectAttempts = 0;
          _stopPolling(); // socket is healthy again
          final text = data is String ? data : utf8.decode(data as List<int>);
          final json = jsonDecode(text) as Map<String, dynamic>;
          if (json['type'] == 'file_ready') {
            final n = json['n'];
            if (n is int && !_fileReadyController.isClosed) {
              _fileReadyController.add(n);
            }
          } else {
            _handle(JobDto.fromJson(json));
          }
        },
        onError: (_) => _scheduleReconnect(),
        onDone: () {
          if (!_terminal) _scheduleReconnect();
        },
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    _sub?.cancel();
    _channel?.sink.close();
    _channel = null;
    if (_disposed || _terminal) return;
    _reconnectAttempts++;
    if (_reconnectAttempts <= 3) {
      // 1s, 2s, 4s backoff.
      final delay = Duration(seconds: 1 << (_reconnectAttempts - 1));
      _reconnectTimer = Timer(delay, _connectWs);
    } else {
      _startPolling(); // give up on the socket; poll the REST endpoint instead
    }
  }

  void _startPolling() {
    if (_disposed || _terminal || _pollTimer != null) return;
    _pollTimer = Timer.periodic(const Duration(seconds: 2), (_) async {
      try {
        _handle(await _api.job(jobId));
      } catch (_) {
        // Keep polling; transient errors are expected while the backend churns.
      }
    });
  }

  void _stopPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  void _handle(JobDto job) {
    if (_disposed) return;
    _controller.add(job);
    if (job.isTerminal) {
      _terminal = true;
      _cleanup();
    }
  }

  void _cleanup() {
    _reconnectTimer?.cancel();
    _stopPolling();
    _sub?.cancel();
    _channel?.sink.close();
  }

  void dispose() {
    _disposed = true;
    _cleanup();
    _controller.close();
    _fileReadyController.close();
  }
}
