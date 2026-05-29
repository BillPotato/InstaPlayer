import 'package:flutter_test/flutter_test.dart';
import 'package:music_app/core/settings.dart';

void main() {
  test('BackendSettings.isConfigured requires both url and key', () {
    expect(const BackendSettings(baseUrl: '', apiKey: '').isConfigured, isFalse);
    expect(const BackendSettings(baseUrl: 'https://x', apiKey: '').isConfigured, isFalse);
    expect(const BackendSettings(baseUrl: 'https://x', apiKey: 'k').isConfigured, isTrue);
  });
}
