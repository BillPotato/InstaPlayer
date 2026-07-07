import { Pressable, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import ReorderableList, { useReorderableDrag } from 'react-native-reorderable-list';
import { TrackRow } from '../components/TrackRow';
import { EmptyState } from '../components/EmptyState';
import { useTheme } from '../theme/useTheme';
import { usePlayerStore, orderedQueueOf, useCurrentTrack } from '../player/playerStore';
import { jumpTo, moveInQueue, removeFromQueue } from '../player/playerService';

function QueueRow({ item, index, pos, colors }) {
  const drag = useReorderableDrag();
  return (
    <TrackRow
      track={item}
      onPress={() => jumpTo(pos + 1 + index)}
      onLongPress={drag}
      right={
        <>
          <Pressable onPress={() => removeFromQueue(pos + 1 + index)} hitSlop={8} style={{ padding: 4 }}>
            <Ionicons name="close" size={20} color={colors.textDim} />
          </Pressable>
          <Pressable onLongPress={drag} delayLongPress={100} hitSlop={8} style={{ padding: 4 }}>
            <Ionicons name="reorder-three-outline" size={20} color={colors.textDim} />
          </Pressable>
        </>
      }
    />
  );
}

export default function QueueScreen() {
  const colors = useTheme();
  const current = useCurrentTrack();
  const pos = usePlayerStore((s) => s.pos);
  const upcoming = usePlayerStore((s) => orderedQueueOf(s).slice(s.pos + 1));

  if (!current) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <EmptyState icon="list" title="Queue is empty" message="Play something to build a queue." />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ReorderableList
        data={upcoming}
        keyExtractor={(t, i) => `${t.id}-${i}`}
        onReorder={({ from, to }) => moveInQueue(pos + 1 + from, pos + 1 + to)}
        ListHeaderComponent={
          <View>
            <Text style={{ color: colors.textDim, fontSize: 13, fontWeight: '700', paddingHorizontal: 16, paddingTop: 12 }}>
              NOW PLAYING
            </Text>
            <TrackRow track={current} onPress={() => {}} />
            {upcoming.length > 0 ? (
              <Text style={{ color: colors.textDim, fontSize: 13, fontWeight: '700', paddingHorizontal: 16, paddingTop: 12 }}>
                NEXT UP · long-press to reorder
              </Text>
            ) : (
              <Text style={{ color: colors.textDim, fontSize: 14, padding: 16 }}>Nothing queued after this.</Text>
            )}
          </View>
        }
        renderItem={({ item, index }) => (
          <QueueRow item={item} index={index} pos={pos} colors={colors} />
        )}
        contentContainerStyle={{ paddingBottom: 24 }}
      />
    </View>
  );
}
