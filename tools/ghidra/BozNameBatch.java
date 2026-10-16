// Names many functions (or data labels) at once from a JSON file: [{"address": "0x4a18cc3c",
// "name": "String_Equals", "notes": "...", "subsystem": "runtime", "confirmed": true}, ...].
// Functions get the name (Class::Method makes the class namespace), the notes as their comment
// and the subsystem and "confirmed" tags ExportBozSymbols reads; a function is created where none
// starts yet. An entry with "label": true names data instead (plate comment for the notes).
// Run ExportBozSymbols and `symbols.py from-json` afterwards to update the game definition.
// @category BOZ
// @menupath Tools.BOZ.Name Batch

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionTag;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.SymbolTable;

import java.io.File;
import java.io.FileReader;

public class BozNameBatch extends GhidraScript {
    private static final String[] SUBSYSTEMS = {
        "engine", "runtime", "state", "entities", "weapons", "rendering", "ui", "audio", "saves",
        "network", "libc", "unknown",
    };

    @Override
    protected void run() throws Exception {
        File in = new File(getScriptArgs()[0]);
        JsonArray items;
        try (FileReader r = new FileReader(in)) {
            items = JsonParser.parseReader(r).getAsJsonArray();
        }
        SymbolTable symbols = currentProgram.getSymbolTable();
        int named = 0, failed = 0;
        for (JsonElement element : items) {
            JsonObject item = element.getAsJsonObject();
            Address address = toAddr(Long.decode(item.get("address").getAsString()));
            String fullName = item.get("name").getAsString();
            String notes = item.has("notes") ? item.get("notes").getAsString() : "";
            try {
                if (item.has("label") && item.get("label").getAsBoolean()) {
                    Namespace space = currentProgram.getGlobalNamespace();
                    String label = fullName;
                    int cut = fullName.lastIndexOf("::");
                    if (cut > 0) {
                        space = getOrCreateNamespace(fullName.substring(0, cut));
                        label = fullName.substring(cut + 2);
                    }
                    ghidra.program.model.symbol.Symbol primary = symbols.getPrimarySymbol(address);
                    boolean force = item.has("force") && item.get("force").getAsBoolean();
                    if (!force && primary != null && primary.getSource() == SourceType.USER_DEFINED
                            && !primary.getName(true).equals(fullName)) {
                        // Keep a name a person gave: put ours back as a secondary label.
                        symbols.createLabel(address, label, space, SourceType.USER_DEFINED);
                        primary.setPrimary();
                        println("kept " + primary.getName(true) + " at " + address + " (not " + fullName + ")");
                        named++;
                        continue;
                    }
                    ghidra.program.model.symbol.Symbol made = symbols.createLabel(address, label, space, SourceType.USER_DEFINED);
                    made.setSource(SourceType.USER_DEFINED);
                    made.setPrimary();
                    String subsystem = item.has("subsystem") ? item.get("subsystem").getAsString() : "";
                    boolean confirmed = item.has("confirmed") && item.get("confirmed").getAsBoolean();
                    String head = (subsystem.isEmpty() ? "" : "@" + subsystem) + (confirmed ? " @confirmed" : "");
                    String plate = head.isBlank() ? notes : head.trim() + "\n" + notes;
                    if (!plate.isEmpty()) {
                        currentProgram.getListing().setComment(address, CodeUnit.PLATE_COMMENT, plate);
                    }
                    named++;
                    continue;
                }
                Function f = getFunctionAt(address);
                if (f == null) {
                    disassemble(address);
                    new CreateFunctionCmd(address).applyTo(currentProgram);
                    f = getFunctionAt(address);
                }
                if (f == null) {
                    println("no function at " + address + " for " + fullName);
                    failed++;
                    continue;
                }
                String name = fullName;
                Namespace namespace = currentProgram.getGlobalNamespace();
                int split = fullName.lastIndexOf("::");
                if (split > 0) {
                    namespace = getOrCreateNamespace(fullName.substring(0, split));
                    name = fullName.substring(split + 2);
                }
                f.setParentNamespace(namespace);
                f.setName(name, SourceType.USER_DEFINED);
                f.getSymbol().setSource(SourceType.USER_DEFINED);
                if (!notes.isEmpty()) {
                    f.setComment(notes);
                }
                String subsystem = item.has("subsystem") ? item.get("subsystem").getAsString() : "";
                if (!subsystem.isEmpty()) {
                    for (FunctionTag tag : f.getTags()) {
                        for (String known : SUBSYSTEMS) {
                            if (tag.getName().equals(known)) {
                                f.removeTag(known);
                            }
                        }
                    }
                    f.addTag(subsystem);
                }
                if (item.has("confirmed") && item.get("confirmed").getAsBoolean()) {
                    f.addTag("confirmed");
                }
                named++;
            } catch (Exception e) {
                println("failed " + fullName + " at " + address + ": " + e.getMessage());
                failed++;
            }
        }
        println("BozNameBatch: " + named + " named, " + failed + " failed");
    }

    private Namespace getOrCreateNamespace(String path) throws Exception {
        Namespace current = currentProgram.getGlobalNamespace();
        for (String part : path.split("::")) {
            Namespace next = currentProgram.getSymbolTable().getNamespace(part, current);
            if (next == null) {
                next = currentProgram.getSymbolTable().createClass(current, part, SourceType.USER_DEFINED);
            }
            current = next;
        }
        return current;
    }
}
