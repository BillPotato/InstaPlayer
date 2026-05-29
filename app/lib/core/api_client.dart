import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../data/models.dart';
import 'settings.dart';

/// Typed HTTP client for the backend. All requests carry the bearer token.
///
/// Requests are issued untyped and parsed explicitly: letting Dio cast the
/// decoded body to a generic `T` triggered a "type 'Null' is not a subtype of
/// type 'String' of 'function result'" crash, so we avoid that path entirely.
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
    if (kDebugMode) {
      _dio.interceptors.add(LogInterceptor(
        requestBody: true,
        responseBody: true,
        error: true,
        logPrint: (o) => debugPrint('[api] $o'),
      ));
    }
  }

  final BackendSettings _settings;
  // Trailing slashes stripped so URL joins always produce a single slash.
  final String _baseUrl;
  late final Dio _dio;

  Dio get raw => _dio;
  BackendSettings get settings => _settings;

  List<Map<String, dynamic>> _asList(Object? data) =>
      (data as List? ?? const []).cast<Map<String, dynamic>>();

  Map<String, dynamic> _asMap(Object? data) =>
      (data as Map).cast<String, dynamic>();

  Future<List<PlaylistDto>> playlists() async {
    final r = await _dio.get<dynamic>('/playlists');
    return _asList(r.data).map(PlaylistDto.fromJson).toList();
  }

  Future<List<TrackDto>> playlistTracks(String playlistId) async {
    final r = await _dio.get<dynamic>('/playlists/$playlistId/tracks');
    return _asList(r.data).map(TrackDto.fromJson).toList();
  }

  Future<List<TrackDto>> tracks({double? updatedSince}) async {
    final r = await _dio.get<dynamic>(
      '/tracks',
      queryParameters: {'updated_since': ?updatedSince},
    );
    return _asList(r.data).map(TrackDto.fromJson).toList();
  }

  Future<JobDto> createJob(String spotifyUrl, {String? preferredSource}) async {
    final r = await _dio.post<dynamic>(
      '/jobs',
      data: {'spotifyUrl': spotifyUrl, 'preferredSource': ?preferredSource},
    );
    return JobDto.fromJson(_asMap(r.data));
  }

  Future<JobDto> job(String jobId) async {
    final r = await _dio.get<dynamic>('/jobs/$jobId');
    return JobDto.fromJson(_asMap(r.data));
  }

  Future<String?> lyrics(String trackId) async {
    try {
      final r = await _dio.get<dynamic>(
        '/tracks/$trackId/lyrics',
        // Endpoint returns text/plain, not JSON.
        options: Options(responseType: ResponseType.plain),
      );
      return r.data?.toString();
    } on DioException catch (e) {
      if (e.response?.statusCode == 404) return null;
      rethrow;
    }
  }

  // ---- URL builders (used by the player, art widgets, downloader) ----
  String fileUrl(String trackId) => '$_baseUrl/tracks/$trackId/file';
  String artUrl(String trackId) => '$_baseUrl/tracks/$trackId/art';

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
