import { useEffect, useMemo, useRef } from 'react';
import { FlatList, ScrollView, Text, View } from 'react-native';
import { parseLyrics, activeLineIndex } from '../lyrics/lrc';
import { usePlayerStore } from '../player/playerStore';
import { seekTo } from '../player/playerService';
import { useTheme } from '../theme/useTheme';

export function LyricsView({ track }) {
  const colors = useTheme();
  const parsed = useMemo(() => parseLyrics(track?.lyrics), [track?.id, track?.lyrics]);
  const positionMs = usePlayerStore((s) => s.currentTime) * 1000;
  const listRef = useRef(null);
  const active = parsed?.synced ? activeLineIndex(parsed.lines, positionMs) : -1;

  useEffect(() => {
    if (active < 0 || !listRef.current) return;
    try {
      listRef.current.scrollToIndex({ index: active, viewPosition: 0.4, animated: true });
    } catch {
      // Layout not ready yet; onScrollToIndexFailed handles it.
    }
  }, [active]);

  if (!parsed) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
        <Text style={{ color: colors.textDim, fontSize: 15 }}>No lyrics for this song</Text>
      </View>
    );
  }

  if (!parsed.synced) {
    return (
      <ScrollView contentContainerStyle={{ padding: 24 }}>
        {parsed.lines.map((l, i) => (
          <Text key={i} style={{ color: colors.text, fontSize: 17, lineHeight: 28 }}>
            {l.text}
          </Text>
        ))}
      </ScrollView>
    );
  }

  return (
    <FlatList
      ref={listRef}
      data={parsed.lines}
      keyExtractor={(_, i) => String(i)}
      contentContainerStyle={{ paddingVertical: 120, paddingHorizontal: 24 }}
      onScrollToIndexFailed={({ index }) => {
        listRef.current?.scrollToOffset({ offset: Math.max(0, index * 38 - 120), animated: true });
      }}
      renderItem={({ item, index }) => (
        <Text
          onPress={() => seekTo(item.timeMs / 1000)}
          style={{
            color: index === active ? colors.accent : index < active ? colors.textDim : colors.text,
            fontSize: 19,
            lineHeight: 34,
            fontWeight: index === active ? '700' : '500',
          }}
        >
          {item.text || '♪'}
        </Text>
      )}
    />
  );
}
