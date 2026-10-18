# Music presets

Drop your own background tracks here (`.mp3`, `.wav`, `.m4a`, `.ogg`,
`.flac`) and they appear in Media Remix under **Music → Music preset**.

Optional metadata in `library.toml` (one block per file):

```toml
[[track]]
file = "piano_memories.mp3"
title = "Piano memories"
mood = "nostalgic"      # nostalgic | cinematic | romantic | upbeat | energetic | calm
volume = 0.3            # suggested music volume
beat_sync = true        # suggested "Cut to the music"
sync = "bars"           # bars | beats | accents | follow | nudge (default: from the mood)
```

"Auto — match the look" picks the first track whose mood matches the
chosen look (Family Memory / Vintage → nostalgic, Cinematic / B&W →
cinematic, Elegant Wedding → romantic, Travel → upbeat, Modern Dynamic →
energetic, Clean → calm).

The built-in presets (Gentle piano, Warm strings, First dance, Sunny
strum, Soft beat, Quiet air) are generated locally by `core/music.py` on
first use into `generated/` — simple generative pieces, free to use, meant
as a starting point until you pick real music. Only use tracks you have the
rights to in videos you publish.

## Search online

**Music → Search online** (opt-in network feature, `core/music_online.py`)
searches Creative Commons catalogues, lets you preview, and saves the track
you pick into `downloads/` next to a `.json` sidecar with title, creator,
licence and the credit line. Downloaded tracks appear in the preset list
and their credit is added to the closing card (checkbox "Add the music
credit to the closing card").

Sources, in the order offered:

1. **Openverse** — CC audio aggregator, no key, licence and attribution in
   every result.
2. **Internet Archive** — netlabel and open-source audio with a licence URL.
3. **Jamendo** — optional; needs `JAMENDO_CLIENT_ID` in `studio/.env`
   (free key from devportal.jamendo.com). Search and preview; the file is
   fetched through Jamendo's own download link only when the artist allows
   it, and the credit names the artist and Jamendo as its API terms ask.
   Jamendo's API is free for non-commercial use.

Licences differ per track: read the licence shown with each result
before using it in a video you publish or monetise. *NC* (non-commercial)
tracks are flagged in amber. *ND* (no derivatives) tracks are flagged in
red and can't be added: putting music under pictures counts as an
adaptation, which ND does not allow.
