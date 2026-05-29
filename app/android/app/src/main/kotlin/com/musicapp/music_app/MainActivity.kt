package com.musicapp.music_app

import com.ryanheise.audioservice.AudioServiceActivity

// audio_service requires the host Activity to be AudioServiceActivity so that
// playback can run in a foreground service detached from the UI.
class MainActivity : AudioServiceActivity()
