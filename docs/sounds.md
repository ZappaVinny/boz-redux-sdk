# Sounds

The **Audio** tab replaces the game's sounds with your own. It has two parts:

- **Game sounds:** every sound your map plays, as slots you can hear and replace.
- **Your sounds:** the processor every sound goes through before it can be used: Import a
  recording, shape it, Preview it as the game will play it, then Save.

Only saved sounds go in slots. Changing a saved sound's settings asks you to Save again; the
slots using it play the new version from the next build.

## Game sounds

Pick **Show the sounds** the first time (it needs the asset library). The list shows each sound
with its length; **Show** filters it:

| Filter | What it shows |
| --- | --- |
| All | Every sound the map plays |
| Replaced | The slots you filled |
| Weapons | Fire, reload, empty click, buy sounds of every weapon |
| Shared | The game's shared sounds: weapons, zombies, power-ups, rounds, buying |
| This map | The base map's own sounds (its dogs, teleporters, music box, ...) |
| Characters | The player characters' voice lines |
| Interface | Menu and interface sounds |

Type in the list's search field to find a sound by name or by what plays it ("Reload",
"ak74u").

Slots are named after what plays them: a weapon's sound is "Thundergun: Fire"; sounds the game
names are named after it ("Carpenter pickup", "Dog spawn"); voice lines start with the
character ("Takeo: …"); a sound many weapons share names the first and how many more ("colt45
+10: Empty click"); the rest show where they live and their number ("Shared 0x…"). **Played
by** lists everything that plays the selected sound.

The game stores weapon sounds in pieces, and the names say which kind:

- **Parts** ("ak74u: Reload part 2 of 4"): a reload is several short recordings (mag out, mag
  in, bolt, ...) played in order with set waits between them (the ak74u's: 350, 350, 550 and
  250 ms), timed to the animation. Replace the part you want to change.
- **Takes** ("ak74u: Fire take 1 of 2"): a shot plays one of a few recordings picked at random,
  so firing does not sound the same every time. Replace every take for a new fire sound (the
  same sound in each is fine).

The **wave view** on the right draws the selected slot's original (grey, top) over your
replacement (orange, bottom); for one of your sounds, the recording (with what the trim cuts
shaded) over the game version. Both share one time scale, with a tick every 0.1 s.

- **Play original** plays the game's sound (as the game stores it).
- **Replace with** puts one of your saved sounds in the slot; **Play** then plays yours.
- **Reset** gives the slot its original back.

A slot is one recording of the game. Everything that plays it plays your sound: a weapon made
from another (New weapon) plays its base's sounds, so replacing one changes both.

## A weapon's own sounds

The Weapons tab's **Sounds** panel gives the selected weapon sounds of its own: for Fire, Last
round, Empty click, Reload, Reload (rounds left), Bought and Bought (player), **Use one sound**
picks one of your saved sounds. The build gives that weapon its own sequence playing just that
recording (with the volume and pitch of the sound it replaces), so:

- one recording can replace a reload the game plays in four parts, with nothing left over;
- the weapon it is made from keeps its own sounds (the idgun's reload leaves the Thundergun's
  alone).

Your recording carries its own timing: line it up with the weapon's reload animation (the wave
view shows its length). **Use the game's** (✕) goes back. Below, the panel lists the game sounds
the weapon still plays, which you can replace as slots (for every weapon that plays them).

## Your sounds

**Import…** reads any file Blender's audio library reads (WAV, MP3, OGG, FLAC, AIFF, ...). The
recording is kept in the project as it is; nothing is changed until you Save.

| Setting | What it does |
| --- | --- |
| Rate | 22050 Hz (better quality; most weapon sounds) or 11025 Hz (half the size; most voices and effects). The game plays only these two. |
| Trim start / end | Seconds cut from the start and the end |
| Normalize | Brings the loudest point to -1 dB first |
| Gain | Then raises or lowers the level (dB) |
| Fade in / out | Seconds of fade at the start and the end |

Stereo recordings are mixed down to mono (the game's sounds are mono). **Recording** plays the
imported file; **Preview (game)** plays it with the settings, through the game's own compression
and back, so you hear exactly what players will. **Save** makes the game version.

## In the game

Build & Run puts your sounds in. A sound of the map's own groups is replaced in the level the
build makes; a shared or character sound is replaced in a copy of the game's group the mod
carries (the client serves a mod's files in place of the game's), so it changes wherever that
mod is enabled. The sound's volume, pitch, polyphony and everything that plays it stay the
game's.

Not yet: the streamed music (mp3 files) and placing new sound emitters.

## Project files

```text
source/sounds/<name>.json        the sound's settings and where it was imported from
source/sounds/<name>/source.wav  the imported recording (as read)
source/sounds/<name>/game.wav    the saved game version (mono, 16-bit, the chosen rate)
source/sounds/slots.json         {"<group path>#0x<sound hash>": "<name>"}: the filled slots
```

The formats and the slot catalog are in `bozkit/sound.py` and
[asset-formats.md](asset-formats.md#sounds-ciwsounddata-ciwsoundspec-csoundsequence).
