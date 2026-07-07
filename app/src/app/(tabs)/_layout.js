import { View } from 'react-native';
import { Redirect } from 'expo-router';
// expo-router v6 vendors react-navigation; Tabs and BottomTabBar both come
// from its tabs entry point.
import { Tabs, BottomTabBar } from 'expo-router/tabs';
import { Ionicons } from '@expo/vector-icons';
import { MiniPlayer } from '../../components/MiniPlayer';
import { useTheme } from '../../theme/useTheme';
import { useSettingsStore } from '../../stores/settingsStore';

export default function TabsLayout() {
  const colors = useTheme();
  const hydrated = useSettingsStore((s) => s.hydrated);
  const setupDone = useSettingsStore((s) => s.setupDone);

  if (hydrated && !setupDone) return <Redirect href="/setup" />;

  return (
    <Tabs
      tabBar={(props) => (
        <View style={{ backgroundColor: colors.background }}>
          <MiniPlayer />
          <BottomTabBar {...props} />
        </View>
      )}
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textDim,
        tabBarStyle: {
          backgroundColor: colors.background,
          borderTopColor: colors.border,
        },
        sceneStyle: { backgroundColor: colors.background },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Home',
          tabBarIcon: ({ color, size, focused }) => (
            <Ionicons name={focused ? 'home' : 'home-outline'} size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="search"
        options={{
          title: 'Search',
          tabBarIcon: ({ color, size, focused }) => (
            <Ionicons name={focused ? 'search' : 'search-outline'} size={size} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="library"
        options={{
          title: 'Your Library',
          tabBarIcon: ({ color, size, focused }) => (
            <Ionicons name={focused ? 'library' : 'library-outline'} size={size} color={color} />
          ),
        }}
      />
    </Tabs>
  );
}
