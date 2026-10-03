// Exports what has been named in the current program to JSON for
// `tools/symbols/symbols.py from-json`, which rewrites gamedef/symbols/boz-1.0.11.toml.
//
// Exported: functions and labels inside the game image whose names were set by a person (or the
// MCP assistant) rather than by analysis or the ELF import, and structs in category /BOZ.
// See ApplyBozSymbols.java for how subsystem and confidence are stored.
// @category BOZ
// @menupath Tools.BOZ.Export Symbol Database

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.Category;
import ghidra.program.model.data.CategoryPath;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeComponent;
import ghidra.program.model.data.Structure;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionTag;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolType;

import java.io.File;
import java.io.FileWriter;
import java.math.BigInteger;

public class ExportBozSymbols extends GhidraScript {
    private static final String[] SUBSYSTEMS = {
        "engine", "runtime", "state", "entities", "weapons", "rendering", "ui", "audio", "saves",
        "network", "libc", "unknown",
    };

    private Address imageStart;
    private Address imageEnd;

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File file = args.length > 0 ? new File(args[0])
                                    : askFile("Write symbol database JSON", "Export");
        imageStart = currentProgram.getImageBase();
        MemoryBlock data = currentProgram.getMemory().getBlock(".data");
        imageEnd = data != null ? data.getEnd() : currentProgram.getMaxAddress();

        JsonObject db = new JsonObject();
        db.add("functions", exportFunctions());
        db.add("globals", exportGlobals());
        db.add("structs", exportStructs());
        try (FileWriter writer = new FileWriter(file)) {
            new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create().toJson(db, writer);
        }
        println(String.format("ExportBozSymbols: %d functions, %d globals, %d structs -> %s",
                db.getAsJsonArray("functions").size(), db.getAsJsonArray("globals").size(),
                db.getAsJsonArray("structs").size(), file));
    }

    private boolean inImage(Address address) {
        return address.compareTo(imageStart) >= 0 && address.compareTo(imageEnd) <= 0;
    }

    private long offset(Address address) {
        return address.subtract(imageStart);
    }

    private boolean isThumb(Address address) {
        Register tmode = currentProgram.getRegister("TMode");
        if (tmode == null) {
            return false;
        }
        BigInteger value = currentProgram.getProgramContext().getValue(tmode, address, false);
        return value != null && value.intValue() == 1;
    }

    private JsonArray exportFunctions() {
        JsonArray out = new JsonArray();
        for (Function function : currentProgram.getFunctionManager().getFunctions(true)) {
            Address entry = function.getEntryPoint();
            if (!inImage(entry) || function.getSymbol().getSource() != SourceType.USER_DEFINED) {
                continue;
            }
            JsonObject item = new JsonObject();
            item.addProperty("name", function.getName(true));  // keeps the class: Class::Method
            item.addProperty("offset", offset(entry));
            item.addProperty("thumb", isThumb(entry));
            if (function.getSignatureSource() == SourceType.USER_DEFINED) {
                item.addProperty("signature", function.getSignature().getPrototypeString());
            }
            String subsystem = "unknown";
            String confidence = "likely";
            for (FunctionTag tag : function.getTags()) {
                if (tag.getName().equals("confirmed")) {
                    confidence = "confirmed";
                }
                for (String known : SUBSYSTEMS) {
                    if (tag.getName().equals(known)) {
                        subsystem = known;
                    }
                }
            }
            item.addProperty("subsystem", subsystem);
            item.addProperty("confidence", confidence);
            String notes = function.getComment();
            if (notes != null && !notes.isBlank()) {
                item.addProperty("notes", notes.strip());
            }
            out.add(item);
        }
        return out;
    }

    private JsonArray exportGlobals() {
        JsonArray out = new JsonArray();
        for (Symbol symbol : currentProgram.getSymbolTable().getAllSymbols(true)) {
            Address address = symbol.getAddress();
            if (symbol.getSymbolType() != SymbolType.LABEL || !symbol.isPrimary() ||
                    symbol.getSource() != SourceType.USER_DEFINED || !inImage(address) ||
                    getFunctionAt(address) != null) {
                continue;
            }
            JsonObject item = new JsonObject();
            item.addProperty("name", symbol.getName(true));
            item.addProperty("offset", offset(address));
            Data data = getDataAt(address);
            if (data != null && data.isDefined()) {
                item.addProperty("type", data.getDataType().getDisplayName());
            }
            String subsystem = "unknown";
            String confidence = "likely";
            String notes = "";
            String plate = currentProgram.getListing().getComment(CodeUnit.PLATE_COMMENT, address);
            if (plate != null) {
                String[] lines = plate.split("\n", 2);
                if (lines[0].startsWith("@")) {
                    for (String token : lines[0].trim().split("\\s+")) {
                        if (token.equals("@confirmed")) {
                            confidence = "confirmed";
                        } else if (token.startsWith("@")) {
                            subsystem = token.substring(1);
                        }
                    }
                    notes = lines.length > 1 ? lines[1] : "";
                } else {
                    notes = plate;
                }
            }
            item.addProperty("subsystem", subsystem);
            item.addProperty("confidence", confidence);
            if (!notes.isBlank()) {
                item.addProperty("notes", notes.strip());
            }
            out.add(item);
        }
        return out;
    }

    private void collectStructs(Category category, JsonArray out) {
        for (DataType type : category.getDataTypes()) {
            if (!(type instanceof Structure)) {
                continue;
            }
            Structure struct = (Structure) type;
            JsonObject item = new JsonObject();
            item.addProperty("name", struct.getName());
            item.addProperty("size", struct.getLength());
            if (struct.getDescription() != null && !struct.getDescription().isBlank()) {
                item.addProperty("notes", struct.getDescription().strip());
            }
            JsonArray fields = new JsonArray();
            for (DataTypeComponent component : struct.getDefinedComponents()) {
                JsonObject field = new JsonObject();
                String name = component.getFieldName();
                field.addProperty("name", name != null ? name : "field_" + Integer.toHexString(component.getOffset()));
                field.addProperty("offset", component.getOffset());
                field.addProperty("type", component.getDataType().getDisplayName());
                if (component.getComment() != null && !component.getComment().isBlank()) {
                    field.addProperty("notes", component.getComment().strip());
                }
                fields.add(field);
            }
            item.add("fields", fields);
            out.add(item);
        }
        for (Category child : category.getCategories()) {
            collectStructs(child, out);
        }
    }

    private JsonArray exportStructs() {
        JsonArray out = new JsonArray();
        Category root = currentProgram.getDataTypeManager().getCategory(new CategoryPath("/BOZ"));
        if (root != null) {
            collectStructs(root, out);
        }
        return out;
    }
}
