import 'package:dio/dio.dart';

import '../data/models.dart';
import 'settings.dart';

/// Typed HTTP client for the backend. All requests carry the bearer token.
///
/// The backend is a stateless downloader: a job downloads FLACs into a temp
/// dir, the client fetches the manifest + files + art, then DELETEs the job.
class ApiClient {
  ApiClient(this._settings)
      : _baseUrl = _settings.baseUrl.replaceAll(RegExp(r'/+$'), '') {
    _dio = Dio(
      BaseOptions(
        baseUrl: _baseUrl,
        headers: {'Authorization': 'Bearer ${_settings.apiKey}'},
        connectTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 60),
      ),
    );
  }

  final BackendSettings _settings;
  final String _baseUrl;
  late final Dio _dio;

  Dio get raw => _dio;
  BackendSettings get settings => _settings;

  Future<JobDto> createJob(String spotifyUrl, {String? preferredSource}) async {
    final r = await _dio.post(
      '/jobs',
      data: {'spotifyUrl': spotifyUrl, 'preferredSource': ?preferredSource},
    );
    return JobDto.fromJson((r.data as Map).cast<String, dynamic>());
  }

  Future<JobDto> job(String jobId) async {
    final r = await _dio.get('/jobs/$jobId');
    return JobDto.fromJson((r.data as Map).cast<String, dynamic>());
  }

  /// The finished job's manifest (playlist name + track metadata).
  Future<ManifestDto> manifest(String jobId) async {
    final r = await _dio.get('/jobs/$jobId/manifest');
    return ManifestDto.fromJson((r.data as Map).cast<String, dynamic>());
  }

  /// Tell the backend we've pulled everything; it deletes the temp files.
  Future<void> deleteJob(String jobId) async {
    await _dio.delete('/jobs/$jobId');
  }

  /// Ask the backend to stop a running job. The backend cancels SpotiFLAC and
  /// publishes a ``cancelled`` status event over the WebSocket.
  Future<void> cancelJob(String jobId) async {
    await _dio.post('/jobs/$jobId/cancel');
  }

  // ---- URL builders (used by the downloader) ----
  String jobFileUrl(String jobId, int n) => '$_baseUrl/jobs/$jobId/files/$n';
  String jobArtUrl(String jobId, int n) => '$_baseUrl/jobs/$jobId/art/$n';

  Map<String, String> get authHeader => {'Authorization': 'Bearer ${_settings.apiKey}'};

  /// ws(s):// URL for the per-job progress socket; token goes in the query
  /// string because browsers/WebSocket clients can't set auth headers.
  Uri jobEventsUri(String jobId) {
    final base = Uri.parse(_baseUrl);
    final scheme = base.scheme == 'https' ? 'wss' : 'ws';
    return base.replace(
      scheme: scheme,
      path: '/jobs/$jobId/events',
      queryParameters: {'token': _settings.apiKey},
    );
  }
}
