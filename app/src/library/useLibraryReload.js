import { useEffect, useRef } from 'react';
import { useFocusEffect } from 'expo-router';

// Drop-in replacement for `useFocusEffect` on screens that show library data.
//
// It loads on focus like `useFocusEffect`, but ALSO re-runs the (memoized)
// effect whenever its dependencies change — e.g. the library `tick` bumped by an
// add / edit / delete — even while the screen stays focused. Plain
// `useFocusEffect` only reliably re-runs on a focus transition, so a delete
// otherwise didn't show until you left the tab and came back. The extra plain
// `useEffect` here reacts to dependency changes deterministically.
//
// Pass a callback wrapped in `useCallback([...deps, tick])`, exactly as you
// would to `useFocusEffect`; it may return a cleanup function.
export function useLibraryReload(effect) {
  useFocusEffect(effect);

  // Re-run on later dependency changes (tick, route params, …). Skip the mount
  // run so it doesn't duplicate the focus load; `useFocusEffect` owns that one.
  const mounted = useRef(false);
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return undefined;
    }
    return effect();
  }, [effect]);
}
