"""The Audio tab: the game's sounds as slots to hear and replace, and the sound processor.

Slots: every sound the map plays (bozkit.sound.catalog), grouped and labelled by what plays it.
Play hears the original; Replace with puts one of your saved sounds in its place; Reset gives
the original back (source/sounds/slots.json).

The processor is the gate every sound goes through: Import brings a recording in (any file
Blender's audio library reads), its settings (trim, level, fades, rate) shape it, Preview plays
it as the game will (through the game's ADPCM and back), Save makes its game version. Only saved
sounds go in slots; change the settings and Save again any time.
"""
from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import link

from ._bozkit import sound
from ._bozkit import hashing
iw_hash = hashing.iw_hash

WORKSPACE = "Audio"
AUDIO_TYPES = (".wav", ".mp3", ".ogg", ".flac", ".aif", ".aiff", ".m4a", ".opus")
NONE = "_none"
_state: dict = {"catalog": None, "key": None, "device": None, "refreshing": False,
                "items": None}
CATEGORY_ITEMS = [("all", "All", "Every sound the map plays"),
                  ("replaced", "Replaced", "The sounds you replaced"),
                  ("weapons", "Weapons", "Fire, reload and other weapon sounds")] + \
    [(key, label, "") for key, label in sound.GROUPS.items()]


def source_dir() -> Path | None:
    root = link.project_root()
    return root / "source" if root else None


def _pack():
    from . import weapons_tab
    return weapons_tab.game_pack()


def _read(path: str):
    pack = _pack()
    if pack is None:
        raise sound.SoundError("the game data is not available (build the asset library)")
    return pack.read(path)


def defs() -> list:
    source = source_dir()
    try:
        return sound.list_defs(source) if source else []
    except sound.SoundError:
        return []


def _weapons(context) -> list:
    """The level's weapons and the project's (new ones play their base's sounds under their own
    name) as (label, values)."""
    from . import weapons_tab

    class Shown:
        def __init__(self, label, values):
            self.label, self.values = label, values
    level = weapons_tab.base_level(context)
    out = [Shown(w.label, w.values) for w in weapons_tab.level_weapons(level)]
    for name in weapons_tab.defs():
        values, _base = weapons_tab.current_values(context, name)
        out.append(Shown(name, values))
    return out


def catalog(context, refresh: bool = False) -> list:
    """The map's sound slots (cached per base level and weapon list)."""
    pack = _pack()
    if pack is None or source_dir() is None:
        return []
    from . import weapons_tab
    base = link.map_scene().boz.base
    key = (base, tuple(sorted(weapons_tab.defs())))
    if refresh or _state["key"] != key or _state["catalog"] is None:
        try:
            _state["catalog"] = sound.catalog(pack.read, pack.names(), base, _weapons(context))
        except (sound.SoundError, OSError, KeyError, ValueError) as exc:
            print(f"boz_suite: sounds: {exc}")
            _state["catalog"] = []
        _state["key"] = key
    return _state["catalog"]


def slot(key: str):
    return next((s for s in catalog(bpy.context) if s.key == key), None)


# --- Playback ---------------------------------------------------------------------------------

def _device():
    import aud
    if _state["device"] is None:
        _state["device"] = aud.Device()
    return _state["device"]


def play_samples(values: list, rate: int) -> bool:
    """Play 16-bit samples (False when there is no sound device, as in background Blender)."""
    try:
        import aud
        import numpy
        stop()
        data = (numpy.asarray(values, dtype=numpy.float32) / 32768.0).reshape(-1, 1)
        _state["handle"] = _device().play(aud.Sound.buffer(data, float(rate)))
        return True
    except Exception as exc:      # noqa: BLE001 - no device, no aud: nothing to hear
        print(f"boz_suite: cannot play sound: {exc}")
        return False


def play_file(path: Path) -> bool:
    try:
        import aud
        stop()
        _state["handle"] = _device().play(aud.Sound(str(path)))
        return True
    except Exception as exc:      # noqa: BLE001
        print(f"boz_suite: cannot play sound: {exc}")
        return False


def stop() -> None:
    try:
        if _state["device"] is not None:
            _state["device"].stopAll()
    except Exception:             # noqa: BLE001
        pass


def read_recording(path: Path) -> tuple[list[list[float]], int]:
    """(channels, rate) of any audio file Blender reads."""
    import aud
    found = aud.Sound(str(path))
    rate = int(found.specs[0])
    data = found.data()
    if data.ndim == 1:
        data = data.reshape(-1, 1)
    return [data[:, c].tolist() for c in range(data.shape[1])], rate


# --- The wave view ----------------------------------------------------------------------------

WAVE_IMAGE = "BOZ Sound"
WAVE_SIZE = (1600, 400)
BACKGROUND = (0.09, 0.09, 0.1, 1.0)
TOP_COLOUR = (0.62, 0.66, 0.72, 1.0)      # the original / the recording
BOTTOM_COLOUR = (0.95, 0.6, 0.2, 1.0)     # yours / as the game plays it
SHADE = (0.05, 0.05, 0.055, 1.0)          # trimmed away


def wave_image():
    image = bpy.data.images.get(WAVE_IMAGE)
    if image is None or tuple(image.size) != WAVE_SIZE:
        if image is not None:
            bpy.data.images.remove(image)
        image = bpy.data.images.new(WAVE_IMAGE, *WAVE_SIZE, alpha=False)
    return image


def show_wave(top=None, bottom=None, trim=(0.0, 0.0)) -> None:
    """Draw (samples, rate) *top* over *bottom* on one time scale (ticks every 0.1 s, longer
    every second); *trim* (start, end seconds) shades what the top's trim cuts away. Shown in the
    Audio tab's image area."""
    try:
        import numpy
    except ImportError:
        return
    width, height = WAVE_SIZE
    pixels = numpy.empty((height, width, 4), dtype=numpy.float32)
    pixels[:] = BACKGROUND
    lanes = [(top, TOP_COLOUR, height // 2, height), (bottom, BOTTOM_COLOUR, 0, height // 2)]
    seconds = max([len(f[0]) / f[1] for f in (top, bottom) if f is not None and len(f[0])] or [1.0])
    rows = numpy.arange(height)[:, None]
    for found, colour, low, high in lanes:
        middle, half = (low + high) // 2, (high - low) // 2 - 6
        pixels[middle, :] = (0.25, 0.25, 0.28, 1.0)
        if found is None or not len(found[0]):
            continue
        values, rate = numpy.asarray(found[0], dtype=numpy.float32) / 32768.0, found[1]
        used = max(1, min(width, int(round(width * (len(values) / rate) / seconds))))
        if found is top and any(trim):
            start = int(width * min(trim[0], seconds) / seconds)
            end = int(width * max(0.0, len(values) / rate - trim[1]) / seconds)
            pixels[low:high, :start] = SHADE
            pixels[low:high, end:used] = SHADE
        edges = numpy.linspace(0, len(values), used + 1).astype(int)
        tops = numpy.array([values[a:max(b, a + 1)].max() for a, b in zip(edges[:-1], edges[1:])])
        bottoms = numpy.array([values[a:max(b, a + 1)].min() for a, b in zip(edges[:-1], edges[1:])])
        upper = (middle + tops * half).astype(int)
        lower = (middle + bottoms * half).astype(int)
        mask = (rows >= lower[None, :]) & (rows <= upper[None, :])
        lane = pixels[:, :used]
        lane[mask] = colour
    for tenth in range(1, int(seconds * 10) + 1):
        x = int(width * tenth / 10 / seconds)
        if x < width:
            size = 14 if tenth % 10 == 0 else 6
            pixels[height // 2 - size:height // 2 + size, x] = (0.45, 0.45, 0.5, 1.0)
    image = wave_image()
    image.pixels.foreach_set(pixels.ravel())
    image.update()
    for window in bpy.context.window_manager.windows:
        if window.workspace.name != WORKSPACE:
            continue
        for area in window.screen.areas:
            if area.type == "IMAGE_EDITOR":
                area.spaces.active.image = image
                area.tag_redraw()


def _wave_of_slot(key: str) -> None:
    source = source_dir()
    try:
        original = sound.original_samples(_read, key)
    except (sound.SoundError, OSError, KeyError):
        original = None
    mine = None
    name = sound.load_slots(source).get(key) if source else None
    if name and sound.is_saved(source, name):
        channels, rate = sound.read_wav(sound.game_wav(source, name))
        mine = ([int(v * 32767) for v in channels[0]], rate)
    show_wave(original, mine)


def _wave_of_sound(name: str, preview=None) -> None:
    source = source_dir()
    if source is None:
        return
    try:
        channels, rate = sound.read_wav(sound.source_wav(source, name))
    except (OSError, sound.SoundError, EOFError):
        return
    mono = [int(sum(c[i] for c in channels) / len(channels) * 32767) for i in range(len(channels[0]))]
    if preview is None and sound.is_saved(source, name):
        saved, saved_rate = sound.read_wav(sound.game_wav(source, name))
        preview = ([int(v * 32767) for v in saved[0]], saved_rate)
    settings = link.map_scene().boz_sound_settings
    show_wave((mono, rate), preview, (settings.trim_start, settings.trim_end))


def _slot_selected(self, context):
    if _state["refreshing"]:
        return
    item = selected_slot(link.map_scene())
    if item is not None:
        _wave_of_slot(item.key)


# --- Lists ------------------------------------------------------------------------------------

class BOZ_SoundSlot(PropertyGroup):
    key: StringProperty()
    label: StringProperty()
    category: StringProperty()
    seconds: FloatProperty()
    users: StringProperty()
    replaced: StringProperty()


class BOZ_SoundItem(PropertyGroup):
    saved: BoolProperty()


def _settings_changed(self, context):
    if _state["refreshing"]:
        return
    _state["preview"] = None


class BOZ_SoundSettings(PropertyGroup):
    rate: EnumProperty(name="Rate", items=[("22050", "22050 Hz", "The game's better quality (most "
                                                         "weapon sounds)"),
                                           ("11025", "11025 Hz", "Half the size (most voices and "
                                                                 "effects)")],
                       update=_settings_changed)
    trim_start: FloatProperty(name="Trim start", min=0.0, soft_max=10.0, unit="TIME_ABSOLUTE",
                              description="Seconds cut from the start", update=_settings_changed)
    trim_end: FloatProperty(name="Trim end", min=0.0, soft_max=10.0, unit="TIME_ABSOLUTE",
                            description="Seconds cut from the end", update=_settings_changed)
    normalize: BoolProperty(name="Normalize", default=True,
                            description="Bring the loudest point to -1 dB before the gain",
                            update=_settings_changed)
    gain_db: FloatProperty(name="Gain", soft_min=-24.0, soft_max=12.0, subtype="NONE",
                           description="Level change in dB", update=_settings_changed)
    fade_in: FloatProperty(name="Fade in", min=0.0, soft_max=2.0, unit="TIME_ABSOLUTE",
                           update=_settings_changed)
    fade_out: FloatProperty(name="Fade out", min=0.0, soft_max=2.0, unit="TIME_ABSOLUTE",
                            update=_settings_changed)


def _from_settings(settings) -> sound.Settings:
    return sound.Settings(int(settings.rate), settings.trim_start, settings.trim_end,
                          settings.gain_db, settings.normalize, settings.fade_in,
                          settings.fade_out)


def _load_settings(settings, values: sound.Settings) -> None:
    _state["refreshing"] = True
    try:
        settings.rate = str(values.rate) if values.rate in sound.RATES else "22050"
        settings.trim_start, settings.trim_end = values.trim_start, values.trim_end
        settings.normalize, settings.gain_db = values.normalize, values.gain_db
        settings.fade_in, settings.fade_out = values.fade_in, values.fade_out
    finally:
        _state["refreshing"] = False


def selected_sound(scene):
    index = scene.boz_sound_index
    return scene.boz_sounds[index] if 0 <= index < len(scene.boz_sounds) else None


def selected_slot(scene):
    index = scene.boz_sound_slot_index
    return scene.boz_sound_slots[index] if 0 <= index < len(scene.boz_sound_slots) else None


def _sound_selected(self, context):
    if _state["refreshing"]:
        return
    item = selected_sound(link.map_scene())
    source = source_dir()
    if item is None or source is None:
        return
    try:
        _load_settings(link.map_scene().boz_sound_settings, sound.load_def(source, item.name).settings)
    except sound.SoundError:
        pass
    _wave_of_sound(item.name)


def refresh_sounds(context, keep: str | None = None) -> None:
    scene = link.map_scene()
    keep = keep or (selected_sound(scene).name if selected_sound(scene) else None)
    source = source_dir()
    _state["refreshing"] = True
    try:
        scene.boz_sounds.clear()
        for d in defs():
            item = scene.boz_sounds.add()
            item.name = d.name
            item.saved = sound.is_saved(source, d.name)
        names = [i.name for i in scene.boz_sounds]
        scene.boz_sound_index = names.index(keep) if keep in names else min(
            scene.boz_sound_index, len(names) - 1)
    finally:
        _state["refreshing"] = False
    _state["items"] = None
    _sound_selected(None, context)


def refresh_slots(context, refresh: bool = False) -> None:
    scene = link.map_scene()
    keep = selected_slot(scene).key if selected_slot(scene) else None
    source = source_dir()
    replaced = sound.load_slots(source) if source else {}
    category = scene.boz_sound_category
    _state["refreshing"] = True
    try:
        scene.boz_sound_slots.clear()
        for found in catalog(context, refresh):
            if category == "replaced" and found.key not in replaced:
                continue
            if category == "weapons" and not any(": " in u for u in found.users):
                continue
            if category not in ("all", "replaced", "weapons") and found.category != category:
                continue
            item = scene.boz_sound_slots.add()
            item.key, item.label, item.category = found.key, found.label, found.category
            item.seconds, item.users = found.seconds, ", ".join(found.users)
            item.replaced = replaced.get(found.key, "")
        keys = [i.key for i in scene.boz_sound_slots]
        scene.boz_sound_slot_index = keys.index(keep) if keep in keys else 0
    finally:
        _state["refreshing"] = False


def _category_changed(self, context):
    refresh_slots(context)


def refresh(context) -> None:
    refresh_sounds(context)
    refresh_slots(context)


def _sound_items(self, context):
    if _state["items"] is None:
        source = source_dir()
        _state["items"] = [(NONE, "Pick a saved sound", "")] + [
            (d.name, d.name, "") for d in defs() if source and sound.is_saved(source, d.name)]
    return _state["items"]


# --- Operators --------------------------------------------------------------------------------

def _clean_name(text: str) -> str:
    import re
    name = re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_") or "sound"
    if not name[0].isalpha():
        name = "s_" + name
    return name[:32]


class BOZ_OT_sound_import(Operator):
    bl_idname = "boz.sound_import"
    bl_label = "Import…"
    bl_description = "Bring in a recording (WAV, MP3, OGG, FLAC, ...) to shape and save as a game sound"

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default=";".join(f"*{t}" for t in AUDIO_TYPES), options={"HIDDEN"})
    name: StringProperty(name="Name", description="The sound's name (empty: from the file)")

    def invoke(self, context, event):
        if source_dir() is None:
            self.report({"ERROR"}, "Open a project first")
            return {"CANCELLED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        source = source_dir()
        path = Path(self.filepath)
        if source is None or not path.is_file():
            self.report({"ERROR"}, "Pick an audio file")
            return {"CANCELLED"}
        name = _clean_name(self.name or path.stem)
        taken = {d.name for d in defs()}
        base, number = name, 1
        while name in taken:
            number += 1
            name = f"{base[:29]}_{number}"
        try:
            channels, rate = read_recording(path)
            settings = sound.Settings(rate=11025 if rate <= 11025 else 22050)
            sound.import_recording(source, sound.SoundDef(name, str(path), settings), channels, rate)
        except Exception as exc:  # noqa: BLE001 - aud raises plain errors for unreadable files
            self.report({"ERROR"}, f"Cannot read {path.name}: {exc}")
            return {"CANCELLED"}
        refresh_sounds(context, keep=name)
        self.report({"INFO"}, f"Imported {name}: shape it, Preview, then Save")
        return {"FINISHED"}


class BOZ_OT_sound_preview(Operator):
    bl_idname = "boz.sound_preview"
    bl_label = "Preview"
    bl_description = "Play the sound with these settings as the game will play it"

    original: BoolProperty(default=False, description="Play the imported recording as it is")

    def execute(self, context):
        scene = link.map_scene()
        item, source = selected_sound(scene), source_dir()
        if item is None or source is None:
            return {"CANCELLED"}
        if self.original:
            play_file(sound.source_wav(source, item.name))
            return {"FINISHED"}
        try:
            values, rate = sound.preview(source, item.name, _from_settings(scene.boz_sound_settings))
        except (sound.SoundError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        play_samples(values, rate)
        _wave_of_sound(item.name, (values, rate))
        self.report({"INFO"}, f"{item.name}: {len(values) / rate:.2f} s at {rate} Hz")
        return {"FINISHED"}


class BOZ_OT_sound_save(Operator):
    bl_idname = "boz.sound_save"
    bl_label = "Save"
    bl_description = "Make this sound's game version with these settings: it can then go in slots"

    def execute(self, context):
        scene = link.map_scene()
        item, source = selected_sound(scene), source_dir()
        if item is None or source is None:
            return {"CANCELLED"}
        try:
            found = sound.load_def(source, item.name)
            found.settings = _from_settings(scene.boz_sound_settings)
            values = sound.save(source, found)
        except (sound.SoundError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        refresh_sounds(context, keep=item.name)
        refresh_slots(context)
        self.report({"INFO"}, f"Saved {item.name} ({len(values) / found.settings.rate:.2f} s)")
        return {"FINISHED"}


class BOZ_OT_sound_remove(Operator):
    bl_idname = "boz.sound_remove"
    bl_label = "Remove sound"
    bl_description = "Delete this sound from the project (the slots using it play the original again)"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        item, source = selected_sound(link.map_scene()), source_dir()
        if item is None or source is None:
            return {"CANCELLED"}
        sound.delete(source, item.name)
        refresh(context)
        return {"FINISHED"}


class BOZ_OT_sound_slot_play(Operator):
    bl_idname = "boz.sound_slot_play"
    bl_label = "Play"
    bl_description = "Play this slot's original game sound (or your replacement)"

    key: StringProperty()
    mine: BoolProperty(default=False)

    def execute(self, context):
        source = source_dir()
        key = self.key or (selected_slot(link.map_scene()).key if selected_slot(link.map_scene()) else "")
        if not key or source is None:
            return {"CANCELLED"}
        if self.mine:
            name = sound.load_slots(source).get(key)
            if not name:
                return {"CANCELLED"}
            play_file(sound.game_wav(source, name))
            return {"FINISHED"}
        try:
            values, rate = sound.original_samples(_read, key)
        except (sound.SoundError, OSError, KeyError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        play_samples(values, rate)
        _wave_of_slot(key)
        return {"FINISHED"}


class BOZ_OT_sound_stop(Operator):
    bl_idname = "boz.sound_stop"
    bl_label = "Stop"
    bl_description = "Stop playing"

    def execute(self, context):
        stop()
        return {"FINISHED"}


class BOZ_OT_sound_slot_replace(Operator):
    bl_idname = "boz.sound_slot_replace"
    bl_label = "Replace with"
    bl_description = "Put one of your saved sounds in place of this game sound"
    bl_property = "sound"

    key: StringProperty()
    sound: EnumProperty(items=_sound_items)

    def invoke(self, context, event):
        _state["items"] = None
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        source = source_dir()
        key = self.key or (selected_slot(link.map_scene()).key if selected_slot(link.map_scene()) else "")
        if not key or source is None or self.sound == NONE:
            return {"CANCELLED"}
        slots = sound.load_slots(source)
        slots[key] = self.sound
        sound.save_slots(source, slots)
        refresh_slots(context)
        _wave_of_slot(key)
        return {"FINISHED"}


class BOZ_OT_sound_slot_reset(Operator):
    bl_idname = "boz.sound_slot_reset"
    bl_label = "Reset"
    bl_description = "Play the original game sound here again"

    key: StringProperty()

    def execute(self, context):
        source = source_dir()
        key = self.key or (selected_slot(link.map_scene()).key if selected_slot(link.map_scene()) else "")
        if not key or source is None:
            return {"CANCELLED"}
        slots = sound.load_slots(source)
        slots.pop(key, None)
        sound.save_slots(source, slots)
        refresh_slots(context)
        return {"FINISHED"}


class BOZ_OT_sounds_refresh(Operator):
    bl_idname = "boz.sounds_refresh"
    bl_label = "Show the sounds"
    bl_description = "Read the map's sounds and the project's"

    def execute(self, context):
        refresh_sounds(context)
        refresh_slots(context, refresh=True)
        return {"FINISHED"}


# --- Panels -----------------------------------------------------------------------------------

class BOZ_UL_sound_slots(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        row = layout.row(align=True)
        row.label(text=item.label, icon="FILE_REFRESH" if item.replaced else "SPEAKER")
        if item.replaced:
            row.label(text=f"→ {item.replaced}")
        row.label(text=f"{item.seconds:.2f} s")
        row.operator(BOZ_OT_sound_slot_play.bl_idname, text="", icon="PLAY").key = item.key

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flags = [self.bitflag_filter_item] * len(items)
        if self.filter_name:
            text = self.filter_name.lower()
            flags = [self.bitflag_filter_item if text in (i.label + " " + i.users).lower() else 0
                     for i in items]
        return flags, []


class BOZ_UL_sounds(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0):
        layout.label(text=item.name if item.saved else f"{item.name}  (not saved)",
                     icon="CHECKMARK" if item.saved else "ERROR")


class _SoundsPanel:
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    @classmethod
    def poll(cls, context):
        return context.workspace is not None and context.workspace.name == WORKSPACE


class BOZ_PT_sound_slots(_SoundsPanel, Panel):
    bl_idname = "BOZ_PT_sound_slots"
    bl_label = "Game sounds"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if source_dir() is None:
            layout.label(text="Open a project to replace sounds", icon="INFO")
            return
        if _pack() is None:
            layout.label(text="Build the asset library in the launcher to hear the game's sounds",
                         icon="ERROR")
            return
        if not len(scene.boz_sound_slots):
            layout.prop(scene, "boz_sound_category", text="")
            layout.operator(BOZ_OT_sounds_refresh.bl_idname, icon="FILE_REFRESH")
            return
        layout.prop(scene, "boz_sound_category", expand=False, text="Show")
        layout.label(text="Wave view: grey the original, orange yours", icon="INFO")
        layout.template_list("BOZ_UL_sound_slots", "", scene, "boz_sound_slots", scene,
                             "boz_sound_slot_index", rows=10)
        item = selected_slot(scene)
        if item is None:
            return
        box = layout.box()
        box.label(text=item.label, icon="SPEAKER")
        if item.users and item.users != item.label:
            box.label(text=f"Played by: {item.users}")
        row = box.row(align=True)
        op = row.operator(BOZ_OT_sound_slot_play.bl_idname, text="Play original", icon="PLAY")
        op.key, op.mine = item.key, False
        if item.replaced:
            op = row.operator(BOZ_OT_sound_slot_play.bl_idname, text=f"Play {item.replaced}",
                              icon="PLAY")
            op.key, op.mine = item.key, True
        row.operator(BOZ_OT_sound_stop.bl_idname, text="", icon="PAUSE")
        row = box.row(align=True)
        row.operator(BOZ_OT_sound_slot_replace.bl_idname, icon="FILE_REFRESH").key = item.key
        if item.replaced:
            row.operator(BOZ_OT_sound_slot_reset.bl_idname, icon="LOOP_BACK").key = item.key


class BOZ_PT_sound_processor(_SoundsPanel, Panel):
    bl_idname = "BOZ_PT_sound_processor"
    bl_label = "Your sounds"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        scene = link.map_scene()
        if source_dir() is None:
            return
        row = layout.row()
        row.template_list("BOZ_UL_sounds", "", scene, "boz_sounds", scene, "boz_sound_index", rows=4)
        column = row.column(align=True)
        column.operator(BOZ_OT_sound_import.bl_idname, text="", icon="IMPORT")
        column.operator(BOZ_OT_sound_remove.bl_idname, text="", icon="REMOVE")
        layout.operator(BOZ_OT_sound_import.bl_idname, icon="IMPORT")
        item = selected_sound(scene)
        if item is None:
            layout.label(text="Import a recording, shape it, Preview, then Save", icon="INFO")
            return
        settings = scene.boz_sound_settings
        box = layout.box()
        box.label(text=item.name, icon="SOUND")
        column = box.column(align=True)
        column.prop(settings, "rate")
        row = column.row(align=True)
        row.prop(settings, "trim_start")
        row.prop(settings, "trim_end")
        row = column.row(align=True)
        row.prop(settings, "normalize")
        row.prop(settings, "gain_db")
        row = column.row(align=True)
        row.prop(settings, "fade_in")
        row.prop(settings, "fade_out")
        row = box.row(align=True)
        row.operator(BOZ_OT_sound_preview.bl_idname, text="Recording", icon="PLAY").original = True
        row.operator(BOZ_OT_sound_preview.bl_idname, text="Preview (game)", icon="PLAY").original = False
        row.operator(BOZ_OT_sound_stop.bl_idname, text="", icon="PAUSE")
        changed = False
        source = source_dir()
        try:
            changed = sound.load_def(source, item.name).settings != _from_settings(settings)
        except sound.SoundError:
            pass
        row = box.row()
        row.scale_y = 1.3
        label = "Save" if item.saved and not changed else ("Save changes" if item.saved else "Save")
        row.operator(BOZ_OT_sound_save.bl_idname, text=label, icon="CHECKMARK")
        if not item.saved:
            box.label(text="Not saved yet: only saved sounds go in slots", icon="ERROR")
        elif changed:
            box.label(text="Settings changed: Save to use them", icon="INFO")


def _weapon_fields():
    from ._bozkit import weapons as wp
    return [(f.key, f.label) for f in wp.FIELDS if f.kind == "sound"]


class BOZ_OT_weapon_sound_set(Operator):
    bl_idname = "boz.weapon_sound_set"
    bl_label = "Use one sound"
    bl_description = ("Give this weapon one sound of its own here (its own sequence: the weapon "
                      "it is made from keeps its sounds)")
    bl_property = "sound"

    field: StringProperty()
    sound: EnumProperty(items=_sound_items)

    def invoke(self, context, event):
        _state["items"] = None
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        from . import weapons_tab
        item = weapons_tab.selected(link.map_scene())
        if item is None or not self.field or self.sound == NONE:
            return {"CANCELLED"}
        weapon = weapons_tab.weapon_def(context, item.name)
        weapon.sounds = dict(weapon.sounds, **{self.field: self.sound})
        weapons_tab.save(context, weapon)
        return {"FINISHED"}


class BOZ_OT_weapon_sound_clear(Operator):
    bl_idname = "boz.weapon_sound_clear"
    bl_label = "Use the game's"
    bl_description = "This weapon plays the game's sound here again"

    field: StringProperty()

    def execute(self, context):
        from . import weapons_tab
        item = weapons_tab.selected(link.map_scene())
        if item is None:
            return {"CANCELLED"}
        weapon = weapons_tab.weapon_def(context, item.name)
        weapon.sounds = {k: v for k, v in weapon.sounds.items() if k != self.field}
        weapons_tab.save(context, weapon)
        return {"FINISHED"}


class BOZ_OT_weapon_sound_play(Operator):
    bl_idname = "boz.weapon_sound_play"
    bl_label = "Play"
    bl_description = "Play the weapon's own sound"

    sound: StringProperty()

    def execute(self, context):
        source = source_dir()
        if source is None or not sound.is_saved(source, self.sound):
            return {"CANCELLED"}
        play_file(sound.game_wav(source, self.sound))
        try:
            channels, rate = sound.read_wav(sound.game_wav(source, self.sound))
            show_wave(None, ([int(v * 32767) for v in channels[0]], rate))
        except (OSError, sound.SoundError):
            pass
        return {"FINISHED"}


class BOZ_PT_weapon_sounds(Panel):
    """The selected weapon's sounds in the Weapons tab (the same slots as the Audio tab)."""
    bl_idname = "BOZ_PT_weapon_sounds"
    bl_label = "Sounds"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 90

    @classmethod
    def poll(cls, context):
        from . import weapons_tab
        return (context.workspace is not None and context.workspace.name == "Weapons"
                and weapons_tab.selected(link.map_scene()) is not None)

    def draw(self, context):
        from . import weapons_tab
        layout = self.layout
        if _pack() is None or source_dir() is None:
            layout.label(text="Needs the asset library and a project", icon="INFO")
            return
        item = weapons_tab.selected(link.map_scene())
        weapon = weapons_tab.weapon_def(context, item.name)
        box = layout.box()
        box.label(text="Its own sounds (one recording each, this weapon only)", icon="SOUND")
        for key, label in _weapon_fields():
            row = box.row(align=True)
            own = weapon.sounds.get(key)
            row.label(text=label)
            if own:
                row.label(text=f"→ {own}", icon="CHECKMARK" if sound.is_saved(source_dir(), own)
                          else "ERROR")
                row.operator(BOZ_OT_weapon_sound_play.bl_idname, text="", icon="PLAY").sound = own
                row.operator(BOZ_OT_weapon_sound_set.bl_idname, text="", icon="FILE_REFRESH").field = key
                row.operator(BOZ_OT_weapon_sound_clear.bl_idname, text="", icon="X").field = key
            else:
                row.label(text="the game's")
                row.operator(BOZ_OT_weapon_sound_set.bl_idname, text="Use one sound").field = key
        prefixes = (f"{item.name}: ", f"{weapons_tab.label_of(context, item.name)}: ")
        mine = [s for s in catalog(context) if any(u.startswith(prefixes) for u in s.users)]
        if not mine:
            return
        layout.label(text="The game's sounds it plays (replacing one changes it for all):")
        replaced = sound.load_slots(source_dir())
        for found in mine:
            title = next((u for u in found.users if u.startswith(prefixes)), found.label)
            if any(title.endswith(f": {label}") and key in weapon.sounds
                   for key, label in _weapon_fields()):
                continue        # it plays its own sound there
            row = layout.row(align=True)
            row.label(text=title, icon="FILE_REFRESH" if found.key in replaced else "SPEAKER")
            if found.key in replaced:
                row.label(text=f"→ {replaced[found.key]}")
            op = row.operator(BOZ_OT_sound_slot_play.bl_idname, text="", icon="PLAY")
            op.key, op.mine = found.key, found.key in replaced
            row.operator(BOZ_OT_sound_slot_replace.bl_idname, text="", icon="FILE_REFRESH").key = found.key
            if found.key in replaced:
                row.operator(BOZ_OT_sound_slot_reset.bl_idname, text="", icon="LOOP_BACK").key = found.key
            others = [u for u in found.users if not u.startswith(prefixes)]
            if others:
                layout.label(text=f"   Also played by: {', '.join(others[:3])}"
                                  f"{'…' if len(others) > 3 else ''}")


CLASSES = (BOZ_SoundSlot, BOZ_SoundItem, BOZ_SoundSettings, BOZ_OT_sound_import,
           BOZ_OT_sound_preview, BOZ_OT_sound_save, BOZ_OT_sound_remove, BOZ_OT_sound_slot_play,
           BOZ_OT_sound_stop, BOZ_OT_sound_slot_replace, BOZ_OT_sound_slot_reset,
           BOZ_OT_sounds_refresh, BOZ_UL_sound_slots, BOZ_UL_sounds, BOZ_PT_sound_slots,
           BOZ_PT_sound_processor, BOZ_OT_weapon_sound_set, BOZ_OT_weapon_sound_clear,
           BOZ_OT_weapon_sound_play, BOZ_PT_weapon_sounds)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.boz_sound_slots = CollectionProperty(type=BOZ_SoundSlot)
    bpy.types.Scene.boz_sound_slot_index = IntProperty(update=_slot_selected)
    bpy.types.Scene.boz_sound_category = EnumProperty(name="Sounds", items=CATEGORY_ITEMS,
                                                      update=_category_changed)
    bpy.types.Scene.boz_sounds = CollectionProperty(type=BOZ_SoundItem)
    bpy.types.Scene.boz_sound_index = IntProperty(update=_sound_selected)
    bpy.types.Scene.boz_sound_settings = PointerProperty(type=BOZ_SoundSettings)


def unregister():
    stop()
    for name in ("boz_sound_settings", "boz_sound_index", "boz_sounds", "boz_sound_category",
                 "boz_sound_slot_index", "boz_sound_slots"):
        delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
