# Contributing to the game definition

The game definition ([boz-redux-gamedef](https://github.com/ZappaVinny/boz-redux-gamedef), the
`gamedef/` submodule) is what mods and the standard lib use to find game functions and data by
name. This page is for people who want to extend it: how to build an annotated Ghidra project
from your own copy of the game, and how names get from Ghidra into the game definition.

Only knowledge is committed (names, layouts, notes), never the game's code: the Ghidra project,
the converted binary and anything under `re/` stay on your machine (`re/` is gitignored).

## Requirements

- Ghidra 12.1 or newer (Java scripts only, no PyGhidra needed).
- Python 3.11+.
- The game set up by the client ([boz-redux](https://github.com/ZappaVinny/boz-redux): its launcher, or `runtime/scripts/setup-game.sh`), linked into this repo as `game` (`ln -s ../boz-redux game`, see `sdk.toml`).

## Build the project

1. Convert the game image to an ELF:

   ```bash
   python3 tools/ghidra/s3e_to_elf.py game/assets/boz.s3e.unpacked re/boz-1.0.11.elf
   ```

   This also writes `re/boz-1.0.11.elf.code-pointers.txt`, the Thumb functions the game only
   reaches through stored pointers.

2. In Ghidra: **File → New Project** (non-shared) in `re/ghidra`, then **File → Import File** on
   `re/boz-1.0.11.elf` with the defaults, and let auto-analysis run.

3. Add `tools/ghidra` under **Window → Script Manager → Manage Script Directories**. The scripts
   then appear under **Tools → BOZ**.

4. Run **Seed Functions From Code Pointers** (`BozSeedFunctions.java`). It creates about 9,700
   functions analysis misses (callbacks and C++ virtual methods). Then
   **Analysis → Auto Analyze** again.

5. Recover the C++ class map from the game's run-time type information and apply it:

   ```bash
   python3 tools/ghidra/rtti_classes.py game/assets/boz.s3e.unpacked re/classes.json \
       --symbols gamedef/symbols/boz-1.0.11.toml
   ```

   then run **Repair Virtual Functions** (`BozRepairVirtuals.java`) and **Apply Class Map**
   (`ApplyBozClasses.java`) on `re/classes.json`, then **Name Component Tables**
   (`BozNameComponentTables.java`) and **Name Singletons** (`BozNameSingletons.java`), which
   labels the instance global of each of the 65 `CIsSingleton<T>` systems as `T::s_instance`. Every C++ class
   (about 2,400, from game code, the Ideaworks studio layer, Marmalade, Bullet, gameswf and
   DemonWare) becomes a Ghidra class with `typeinfo` and `vtable` labels, and each virtual
   function is named `Class::vf<slot>` in the class that introduces it and tagged `lib:<library>`.
   Destructors (`~Class`, `~Class_deleting`) are found by behaviour: the deleting destructor
   calls the slot before it and then `operator_delete`. That pair is usually slots 0 and 1, but
   not always (`CIsSystemStatic<T>` has it at 9 and 10). Constructors are found by the vtable
   pointer they store into `this` (`Class::Class`). Slots named in the database's
   `[[vslot]]` entries name every override (`CMysteryBox::Init`, `CMysteryBox::OnEvent`),
   including implementations reached through secondary-vtable thunks. The component tables
   script labels each `CIsComponentTable<T>` global as `T::s_table` and names the lookups that
   find an entity's component as `T::FromEntity`. These names are rebuilt from the game at any
   time, so they are not exported; rename one (for example `CMysteryBox::vf24` to
   `CMysteryBox::Update`) and it is. To name a slot for every class at once, add a `[[vslot]]`
   to the database instead.

6. Load the symbol database:

   ```bash
   python3 tools/symbols/symbols.py to-json gamedef/symbols/boz-1.0.11.toml re/symbols.json
   ```

   and run **Apply Symbol Database** (`ApplyBozSymbols.java`) on `re/symbols.json`.

7. Run **Export Reflection** (`ExportBozReflection.java`) with arguments
   `re/reflection.json structs`. It reads the game's own reflection registrations (see below)
   and writes every reflected class, its bases and its named fields to `re/reflection.json`. It
   also creates a structure named after each class (at the class's path, where Ghidra looks for
   the type of `this`), with every field (own and
   inherited) at its offset, and sets `__thiscall` on the class's methods whose signature was
   never set, so decompiled methods read `this->m_Health` instead of raw offsets.
   Finally it names each class's `T::GetClassInfo` and `T::RegisterReflection`. Then refresh the
   SDK schema:

   ```bash
   python3 tools/symbols/symbols.py reflection re/reflection.json gamedef/reflection/boz-1.0.11.toml
   ```

8. Name the hashes and the event bus:
   - **Name Hash Globals** (`BozNameHashGlobals.java`, argument `re/hash-globals.json`) labels
     every global caching `IwHashString("name")`, including the observer event ids registered
     through `SubjectId_Register`, as `hash_<name>`.
   - **Type GOT Pointers** (`BozTypeGotPointers.java`) types the pointer slots code reaches those
     globals through, so the decompiler prints `PTR_hash_SUBJECT_NEW_WAVE` instead of
     `DAT_4a412eec`.
   - **Export Events** (`ExportBozEvents.java`, arguments `re/events.json annotate`) lists who
     sends, subscribes to and handles each `SUBJECT_*` event, and notes it on each function.

   Then refresh the SDK catalog:

   ```bash
   python3 tools/symbols/symbols.py events re/hash-globals.json re/events.json gamedef/events/boz-1.0.11.toml
   ```

9. **Export Console Commands** (`ExportBozCommands.java`, argument `re/commands.json`) lists every
   developer console command (name, id, owning class). **Export Console Variables**
   (`ExportBozCvars.java`, `re/cvars.json`) lists the cvars registered through the
   `Cvar_Register*` wrappers; **Export Direct Console Variables** (`ExportBozDirectCvars.java`,
   `re/cvars-direct.json`) adds the ones registered straight through the console's vtable and the
   names the code only reads. Refresh the catalog and its readable reference:

   ```bash
   python3 tools/symbols/symbols.py console re/cvars.json re/commands.json \
       gamedef/console/boz-1.0.11.toml --direct re/cvars-direct.json
   python3 tools/symbols/symbols.py console-doc gamedef/console/boz-1.0.11.toml \
       tools/symbols/console_notes.toml docs/console-reference.md
   ```

   What each variable or command does, and in-game test results, go in
   `tools/symbols/console_notes.toml`.

10. Optional: **Export Engine Boundary** (`ExportBozEngineBoundary.java`) reports which
   functions call each family of engine imports. **Find String References**
   (`BozFindStringRefs.java`, arguments: hex addresses) lists the functions using a string or
   global; Ghidra's own references miss the game's `ldr` + `add pc` addressing.

### How the reflection data is found

Each reflected class has a registration function that runs at start-up:

```
info = T::GetClassInfo();                      // static CIsClassInfo(&s_info, "T")
ClassRegistry_Add(ClassRegistry_Get(), IwHashString("T"), info);
CIsClassInfo::AddBase(info, Base::GetClassInfo(), offset);
spec = new CIsReflectPropertySpec<float>(spec, info, "m_fov", 0x40, 4, flags);
CIsClassInfo::AddProperty(info, spec);
```

The constructor call is often inlined, leaving stores into the 0x1c-byte spec instead:
+0 vtable (which gives the field type), +8 name, +0x10 flags (2 = network property),
+0x14 offset. The exporter handles both forms. Data resources (`CIsReflectedResource`) store
their fields as a property blob in `.group.bin`. `Serialise` reads it, and slot 6 decodes it
through the class info, so the schema is also the format of the game's gameplay data.

## Save your work to the database

1. Run **Export Symbol Database** (`ExportBozSymbols.java`) to `re/symbols-export.json`.
2. Rewrite the database from it:

   ```bash
   python3 tools/symbols/symbols.py from-json re/symbols-export.json gamedef/symbols/boz-1.0.11.toml
   python3 tools/symbols/symbols.py stats gamedef/symbols/boz-1.0.11.toml
   ```

3. Review `git diff gamedef/symbols` and commit.

Pull before you start and apply the database first, so you export on top of everyone else's work.

## Conventions

- **What gets exported**: functions and labels inside the game image that a person named
  (Ghidra source "User Defined"), plus every struct in the data type category `/BOZ`. Names from
  analysis (`FUN_...`, `DAT_...`) and the ELF import (`PTR_...`, the import stubs) are not.
- **Names**: `Subsystem_Function` for functions (`Weapon_Fire`), `g_name` for globals,
  `s_name` for constant data (strings, tables), `PascalCase` for structs.
- **Subsystem**: a function tag, one of `engine runtime state entities weapons rendering ui
  audio saves network libc unknown`. For a global, put `@subsystem` on the first line of its
  plate comment.
- **Confidence**: add the function tag `confirmed` (or `@confirmed` for a global) only when the
  meaning is proven, by tracing the running game or by unambiguous code. Everything else is
  `likely`.
- **Notes**: the function comment (plate comment above the function) for functions, the rest of
  the plate comment for globals. Say what it does and how you know.
- **Structs**: create them in `/BOZ`; field names and comments are exported.
- Coverage per subsystem is the `[coverage]` table in the database; update it by hand when a
  subsystem's mapping moves forward.
