# Compatibility

BOZ Redux components are versioned separately. This table describes the current development
baseline; a public SDK release is not planned until custom-map support has matured.

| Component | Current baseline | Compatibility contract |
| --- | --- | --- |
| Game | Android 1.0.11, versionCode 1045111 | Exact target |
| Client | v0.1.1 development line | Reads schema 1 gamedef and current mod folders |
| SDK | Unreleased development line | Project schema 1 |
| Gamedef | Schema 1 | Target `boz-1.0.11` |
| Lua | 5.4 | Public client API and `boz.*` source compatibility |
| Blender | Not implemented yet | One LTS version will be selected with the add-on |
| Python | 3.11 or newer | Required by SDK tools |

Changes to the project schema, package format, gamedef schema or public Lua API require migration
notes. Phase milestones may produce CI artifacts, but they are not public releases or compatibility
promises.
