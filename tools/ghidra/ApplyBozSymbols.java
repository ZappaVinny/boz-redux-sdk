// Loads the BOZ Redux symbol database (JSON from `tools/symbols/symbols.py to-json`) into the
// current program: structs (category /BOZ; one named after a class is also merged into the
// class's own structure, used for `this`), function names, signatures, notes and tags, and
// global labels and types. Safe to run again; it overwrites what the database defines.
//
// Conventions shared with ExportBozSymbols.java:
//   - function subsystem and confidence are function tags ("rendering", "confirmed");
//   - global subsystem and confidence are "@rendering @confirmed" tokens on the first line of
//     the label's plate comment, followed by the notes.
// @category BOZ
// @menupath Tools.BOZ.Apply Symbol Database

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.ApplyFunctionSignatureCmd;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.app.util.cparser.C.CParserUtils;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.CategoryPath;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeConflictHandler;
import ghidra.program.model.data.DataTypeManager;
import ghidra.program.model.data.FunctionDefinitionDataType;
import ghidra.program.model.data.Structure;
import ghidra.program.model.data.StructureDataType;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolType;
import ghidra.program.model.util.CodeUnitInsertionException;
import ghidra.program.model.data.DataUtilities;
import ghidra.util.data.DataTypeParser;

import java.io.File;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.List;

public class ApplyBozSymbols extends GhidraScript {
    static final CategoryPath CATEGORY = new CategoryPath("/BOZ");

    private final List<String> problems = new ArrayList<>();
    private DataTypeManager types;
    private DataTypeParser parser;

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File file = args.length > 0 ? new File(args[0]) : askFile("Symbol database JSON", "Apply");
        JsonObject db;
        try (FileReader reader = new FileReader(file)) {
            db = JsonParser.parseReader(reader).getAsJsonObject();
        }
        types = currentProgram.getDataTypeManager();
        parser = new DataTypeParser(types, types, null, DataTypeParser.AllowedDataTypes.ALL);

        int structs = applyStructs(array(db, "structs"));
        int functions = applyFunctions(array(db, "functions"));
        int globals = applyGlobals(array(db, "globals"));
        for (String problem : problems) {
            printerr("ApplyBozSymbols: " + problem);
        }
        println(String.format("ApplyBozSymbols: %d structs, %d functions, %d globals, %d problems",
                structs, functions, globals, problems.size()));
    }

    private static JsonArray array(JsonObject object, String key) {
        return object.has(key) ? object.getAsJsonArray(key) : new JsonArray();
    }

    private static String text(JsonObject object, String key) {
        JsonElement element = object.get(key);
        return element == null || element.isJsonNull() ? "" : element.getAsString();
    }

    private Address address(JsonObject entry) {
        return currentProgram.getImageBase().add(entry.get("offset").getAsLong());
    }

    private DataType parseType(String name) {
        try {
            return parser.parse(name.trim());
        } catch (Exception e) {
            return null;
        }
    }

    // Two passes so structs can point at each other: create them all, then fill the fields.
    private int applyStructs(JsonArray structs) throws Exception {
        for (JsonElement element : structs) {
            JsonObject entry = element.getAsJsonObject();
            String name = text(entry, "name");
            if (types.getDataType(CATEGORY, name) == null) {
                Structure empty = new StructureDataType(CATEGORY, name, 0, types);
                types.addDataType(empty, DataTypeConflictHandler.KEEP_HANDLER);
            }
        }
        for (JsonElement element : structs) {
            JsonObject entry = element.getAsJsonObject();
            String name = text(entry, "name");
            int size = entry.get("size").getAsInt();
            Structure struct = new StructureDataType(CATEGORY, name, size, types);
            struct.setDescription(text(entry, "notes"));
            JsonArray fields = array(entry, "fields");
            for (JsonElement fieldElement : fields) {
                JsonObject field = fieldElement.getAsJsonObject();
                DataType type = parseType(text(field, "type"));
                int offset = field.get("offset").getAsInt();
                if (type == null) {
                    problems.add(name + "." + text(field, "name") + ": unknown type " + text(field, "type"));
                    continue;
                }
                if (offset + type.getLength() > size) {
                    problems.add(name + "." + text(field, "name") + ": past the end of the struct");
                    continue;
                }
                struct.replaceAtOffset(offset, type, type.getLength(), text(field, "name"),
                        text(field, "notes"));
            }
            types.addDataType(struct, DataTypeConflictHandler.REPLACE_HANDLER);
            mergeIntoClassStruct(name, (Structure) types.getDataType(CATEGORY, name));
        }
        return structs.size();
    }

    // A struct named after a class is also merged into the class's own structure (at the class's
    // path, where Ghidra looks for the type of `this` in __thiscall methods). Fields fill only
    // undefined space, so reflected fields (ExportBozReflection) are kept.
    private void mergeIntoClassStruct(String name, Structure from) {
        if (from == null || getNamespace(null, name) == null) {
            return;
        }
        DataType existing = types.getDataType(CategoryPath.ROOT, name);
        Structure target = existing instanceof Structure ? (Structure) existing.copy(types)
                : new StructureDataType(CategoryPath.ROOT, name, 0, types);
        if (target.getLength() < from.getLength()) {
            target.growStructure(from.getLength() - target.getLength());
        }
        for (ghidra.program.model.data.DataTypeComponent c : from.getDefinedComponents()) {
            boolean free = true;
            for (int i = 0; i < c.getLength() && free; i++) {
                ghidra.program.model.data.DataTypeComponent at = target.getComponentContaining(c.getOffset() + i);
                free = at == null || at.getDataType() == DataType.DEFAULT;
            }
            if (free) {
                try {
                    target.replaceAtOffset(c.getOffset(), c.getDataType(), c.getLength(), c.getFieldName(), c.getComment());
                } catch (IllegalArgumentException e) {
                    problems.add(name + "." + c.getFieldName() + ": " + e.getMessage());
                }
            }
        }
        types.addDataType(target, DataTypeConflictHandler.REPLACE_HANDLER);
        // Its methods take that structure as `this`.
        for (ghidra.program.model.symbol.Symbol sym : currentProgram.getSymbolTable().getSymbols(getNamespace(null, name))) {
            if (sym.getSymbolType() != ghidra.program.model.symbol.SymbolType.FUNCTION) {
                continue;
            }
            ghidra.program.model.listing.Function f = (ghidra.program.model.listing.Function) sym.getObject();
            String fn = f.getName();
            if (fn.equals("GetClassInfo") || fn.equals("RegisterReflection") || fn.equals("FromEntity")
                    || f.getSignatureSource() != SourceType.DEFAULT || "__thiscall".equals(f.getCallingConventionName())) {
                continue;
            }
            try {
                f.setCallingConvention("__thiscall");
            } catch (Exception e) {
                problems.add(f.getName(true) + ": " + e.getMessage());
            }
        }
    }

    // Splits "A::B<C::D>::E" into ["A", "B<C::D>", "E"] (same rule as ApplyBozClasses.java).
    static java.util.List<String> scopes(String name) {
        java.util.List<String> parts = new java.util.ArrayList<>();
        int depth = 0;
        int start = 0;
        for (int i = 0; i < name.length(); i++) {
            char c = name.charAt(i);
            if (c == '<') {
                depth++;
            } else if (c == '>') {
                depth--;
            } else if (depth == 0 && c == ':' && i + 1 < name.length() && name.charAt(i + 1) == ':') {
                parts.add(name.substring(start, i));
                start = i + 2;
                i++;
            }
        }
        parts.add(name.substring(start));
        // Ghidra symbol names cannot contain spaces: "Map<int, char>" becomes "Map<int,_char>".
        parts.replaceAll(part -> ghidra.program.model.symbol.SymbolUtilities.replaceInvalidChars(
                part.replace(", ", ","), true));
        return parts;
    }

    // "Class::Method" puts the symbol in that class (created if needed), like the class map does.
    private void setQualifiedName(Symbol symbol, String name) throws Exception {
        java.util.List<String> parts = scopes(name);
        ghidra.program.model.symbol.Namespace parent = currentProgram.getGlobalNamespace();
        ghidra.program.model.symbol.SymbolTable table = currentProgram.getSymbolTable();
        for (int i = 0; i < parts.size() - 1; i++) {
            ghidra.program.model.symbol.Namespace existing = table.getNamespace(parts.get(i), parent);
            parent = existing != null ? existing
                    : table.createClass(parent, parts.get(i), SourceType.USER_DEFINED);
        }
        symbol.setNameAndNamespace(parts.get(parts.size() - 1), parent, SourceType.USER_DEFINED);
    }

    // Names in the database are unique: drop a user label with this name anywhere else (left over
    // from an older database version or a moved symbol).
    private void removeStaleNames(String name, Address keep) {
        java.util.List<String> parts = scopes(name);
        for (Symbol symbol : currentProgram.getSymbolTable().getSymbols(parts.get(parts.size() - 1))) {
            if (!symbol.getAddress().equals(keep) && symbol.getSource() == SourceType.USER_DEFINED &&
                    symbol.getSymbolType() == SymbolType.LABEL && symbol.getName(true).equals(name)) {
                symbol.delete();
            }
        }
    }

    private Function ensureFunction(Address address, boolean thumb) throws Exception {
        Function function = getFunctionAt(address);
        if (function != null) {
            return function;
        }
        if (getInstructionAt(address) == null) {
            new ArmDisassembleCommand(address, null, thumb).applyTo(currentProgram, monitor);
        }
        new CreateFunctionCmd(address).applyTo(currentProgram, monitor);
        return getFunctionAt(address);
    }

    private int applyFunctions(JsonArray functions) throws Exception {
        int applied = 0;
        for (JsonElement element : functions) {
            monitor.checkCancelled();
            JsonObject entry = element.getAsJsonObject();
            String name = text(entry, "name");
            boolean thumb = entry.has("thumb") && entry.get("thumb").getAsBoolean();
            Function function = ensureFunction(address(entry), thumb);
            if (function == null) {
                problems.add(name + ": could not create a function at " + address(entry));
                continue;
            }
            removeStaleNames(name, function.getEntryPoint());
            setQualifiedName(function.getSymbol(), name);
            String signature = text(entry, "signature");
            if (!signature.isEmpty()) {
                try {
                    FunctionDefinitionDataType definition =
                            CParserUtils.parseSignature((ghidra.app.services.DataTypeManagerService) null, currentProgram, signature);
                    if (definition == null) {
                        problems.add(name + ": could not parse signature " + signature);
                    } else {
                        new ApplyFunctionSignatureCmd(function.getEntryPoint(), definition,
                                SourceType.USER_DEFINED).applyTo(currentProgram, monitor);
                        setQualifiedName(function.getSymbol(), name);
                    }
                } catch (Exception e) {
                    problems.add(name + ": signature " + signature + ": " + e.getMessage());
                }
            }
            String notes = text(entry, "notes");
            function.setComment(notes.isEmpty() ? null : notes);
            for (String tag : new String[] {"confirmed"}) {
                function.removeTag(tag);
            }
            String subsystem = text(entry, "subsystem");
            if (!subsystem.isEmpty()) {
                function.addTag(subsystem);
            }
            if ("confirmed".equals(text(entry, "confidence"))) {
                function.addTag("confirmed");
            }
            applied++;
        }
        return applied;
    }

    private int applyGlobals(JsonArray globals) throws Exception {
        int applied = 0;
        for (JsonElement element : globals) {
            monitor.checkCancelled();
            JsonObject entry = element.getAsJsonObject();
            String name = text(entry, "name");
            Address address = address(entry);
            String typeName = text(entry, "type");
            if (!typeName.isEmpty()) {
                DataType type = parseType(typeName);
                if (type == null) {
                    problems.add(name + ": unknown type " + typeName);
                } else {
                    try {
                        DataUtilities.createData(currentProgram, address, type, -1,
                                DataUtilities.ClearDataMode.CLEAR_ALL_CONFLICT_DATA);
                    } catch (CodeUnitInsertionException e) {
                        problems.add(name + ": " + e.getMessage());
                    }
                }
            }
            // Label after the data: clearing conflicting data can drop or move existing labels.
            removeStaleNames(name, address);
            Symbol label = createLabel(address, scopes(name).get(
                    scopes(name).size() - 1), true, SourceType.USER_DEFINED);
            setQualifiedName(label, name);
            StringBuilder plate = new StringBuilder();
            String subsystem = text(entry, "subsystem");
            if (!subsystem.isEmpty()) {
                plate.append('@').append(subsystem);
            }
            if ("confirmed".equals(text(entry, "confidence"))) {
                plate.append(plate.length() > 0 ? " " : "").append("@confirmed");
            }
            String notes = text(entry, "notes");
            if (!notes.isEmpty()) {
                plate.append(plate.length() > 0 ? "\n" : "").append(notes);
            }
            currentProgram.getListing().setComment(address, CodeUnit.PLATE_COMMENT,
                    plate.length() > 0 ? plate.toString() : null);
            applied++;
        }
        return applied;
    }
}
