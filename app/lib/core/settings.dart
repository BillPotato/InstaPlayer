import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Connection settings for the user's self-hosted backend.
class BackendSettings {
  const BackendSettings({required this.baseUrl, required this.apiKey});

  final String baseUrl; // e.g. https://music.example.com
  final String apiKey;

  bool get isConfigured => baseUrl.isNotEmpty && apiKey.isNotEmpty;

  BackendSettings copyWith({String? baseUrl, String? apiKey}) => BackendSettings(
        baseUrl: baseUrl ?? this.baseUrl,
        apiKey: apiKey ?? this.apiKey,
      );

  static const empty = BackendSettings(baseUrl: '', apiKey: '');
}

/// Persists backend settings; the API key lives in the OS secure store.
class SettingsRepository {
  SettingsRepository([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  static const _kBaseUrl = 'backend_base_url';
  static const _kApiKey = 'backend_api_key';

  Future<BackendSettings> load() async {
    final baseUrl = await _storage.read(key: _kBaseUrl) ?? '';
    final apiKey = await _storage.read(key: _kApiKey) ?? '';
    return BackendSettings(baseUrl: baseUrl.trim(), apiKey: apiKey.trim());
  }

  Future<void> save(BackendSettings settings) async {
    await _storage.write(key: _kBaseUrl, value: settings.baseUrl.trim());
    await _storage.write(key: _kApiKey, value: settings.apiKey.trim());
  }
}
