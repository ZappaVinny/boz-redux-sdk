// Applies the C++ class map from tools/ghidra/rtti_classes.py: a Ghidra class per C++ class,
// "typeinfo" and "vtable" labels, vtable slots typed as pointers, and every virtual function
// named Class::vf<slot> (or vf<slot>_off<offset> for secondary vtables) in the class that
// introduces it, tagged with its library (lib:game, lib:marmalade, lib:studio, lib:bullet,
// lib:gameswf, lib:demonware).
//
// Everything is created with source ANALYSIS: it is rebuilt from the game at any time and is not
// exported. Functions a person has named (USER_DEFINED) are never renamed.
// @category BOZ
// @menupath Tools.BOZ.Apply Class Map

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataUtilities;
import ghidra.program.model.data.IntegerDataType;
import ghidra.program.model.data.PointerDataType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;

import java.io.File;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class ApplyBozClasses extends GhidraScript {
    private final Map<String, Namespace> namespaces = new HashMap<>();
    private final Map<String, String> libraries = new HashMap<>();
    private SymbolTable symbols;
    private Address base;
    private int problems;

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File file = args.length > 0 ? new File(args[0]) : askFile("Class map JSON (rtti_classes.py)", "Apply");
        JsonObject map;
        try (FileReader reader = new FileReader(file)) {
            map = JsonParser.parseReader(reader).getAsJsonObject();
        }
        symbols = currentProgram.getSymbolTable();
        base = currentProgram.getImageBase();

        JsonArray classes = map.getAsJsonArray("classes");
        monitor.initialize(classes.size());
        monitor.setMessage("Classes and vtables");
        int vtables = 0;
        for (JsonElement element : classes) {
            monitor.checkCancelled();
            monitor.incrementProgress(1);
            JsonObject entry = element.getAsJsonObject();
            String name = entry.get("name").getAsString();
            libraries.put(name, entry.get("library").getAsString());
            Namespace ns = classNamespace(name);
            if (ns == null) {
                continue;
            }
            label(base.add(entry.get("typeinfo").getAsLong()), "typeinfo", ns);
            for (JsonElement vtableElement : entry.getAsJsonArray("vtables")) {
                JsonObject vtable = vtableElement.getAsJsonObject();
                long offset = -vtable.get("offset_to_top").getAsLong();
                Address address = base.add(vtable.get("address").getAsLong());
                label(address, offset == 0 ? "vtable" : "vtable_off" + Long.toHexString(offset), ns);
                typeVtable(address, vtable.getAsJsonArray("functions").size());
                vtables++;
            }
        }

        JsonArray functions = map.getAsJsonArray("virtual_functions");
        monitor.initialize(functions.size());
        monitor.setMessage("Virtual functions");
        int named = 0;
        int kept = 0;
        for (JsonElement element : functions) {
            monitor.checkCancelled();
            monitor.incrementProgress(1);
            JsonObject entry = element.getAsJsonObject();
            Address address = base.add(entry.get("address").getAsLong());
            Function function = ensureFunction(address, entry.get("thumb").getAsBoolean());
            if (function == null) {
                problems++;
                continue;
            }
            String owner = entry.get("owner").getAsString();
            function.addTag("lib:" + libraries.getOrDefault(owner, "game"));
            SourceType source = function.getSymbol().getSource();
            if (source == SourceType.USER_DEFINED || source == SourceType.IMPORTED) {
                kept++;
                continue;
            }
            Namespace ns = classNamespace(owner);
            if (ns == null) {
                continue;
            }
            try {
                function.setParentNamespace(ns);
                function.setName(entry.get("name").getAsString(), SourceType.ANALYSIS);
                named++;
            } catch (Exception e) {
                problems++;
            }
        }
        int followed = nameThunkTargets(functions);
        println("ApplyBozClasses: " + followed + " implementations named through this-adjusting thunks");
        int[] lifecycle = nameConstructorsAndDestructors(classes, functions);
        println(String.format("ApplyBozClasses: %d classes, %d vtables, %d virtual functions named, "
                + "%d kept (named by a person), %d constructors, %d destructors, %d problems",
                classes.size(), vtables, named, kept, lifecycle[0], lifecycle[1], problems));
    }

    // A secondary vtable entry for an override is a thunk: "sub r0, r0, #offset; b impl". When a
    // vslot name reached the thunk (OnEvent_off38), give the implementation the plain name
    // (OnEvent) if it still only has a generated vf<slot> name.
    private int nameThunkTargets(JsonArray functions) throws Exception {
        int named = 0;
        for (JsonElement element : functions) {
            JsonObject entry = element.getAsJsonObject();
            String name = entry.get("name").getAsString();
            if (entry.get("offset").getAsLong() == 0 || name.startsWith("vf") || !name.contains("_off")) {
                continue;
            }
            Function thunk = getFunctionAt(base.add(entry.get("address").getAsLong()));
            if (thunk == null) {
                continue;
            }
            ghidra.program.model.listing.Instruction first = getInstructionAt(thunk.getEntryPoint());
            ghidra.program.model.listing.Instruction second = first == null ? null : first.getNext();
            if (first == null || second == null || !first.getMnemonicString().startsWith("sub") ||
                    !"r0".equals(first.getDefaultOperandRepresentation(0)) ||
                    !(second.getFlowType().isJump() || second.getFlowType().isCall()) ||
                    second.getFlowType().isConditional()) {  // b.w to a function start is a tail call
                continue;
            }
            Address[] flows = second.getFlows();
            Function target = flows.length == 1 ? getFunctionAt(flows[0]) : null;
            if (target == null || target.getSymbol().getSource() == SourceType.USER_DEFINED ||
                    target.getSymbol().getSource() == SourceType.IMPORTED || !target.getName().startsWith("vf")) {
                continue;
            }
            try {
                target.getSymbol().setNameAndNamespace(name.substring(0, name.indexOf("_off")),
                        target.getParentNamespace(), SourceType.ANALYSIS);
                named++;
            } catch (Exception e) {
                // the class already has a function by that name
            }
        }
        return named;
    }

    // Constructors install the vtable pointer (vtable + 8) of their class, and of each secondary
    // base at its offset; a constructor that inlines its base's constructor installs the base's
    // pointer too, so the most derived class referenced wins. Destructors are found per vtable by
    // behaviour (see below).
    private int[] nameConstructorsAndDestructors(JsonArray classes, JsonArray functions) throws Exception {
        Map<String, JsonObject> byName = new HashMap<>();
        Map<Long, String> classByTypeinfo = new HashMap<>();
        for (JsonElement element : classes) {
            JsonObject entry = element.getAsJsonObject();
            byName.put(entry.get("name").getAsString(), entry);
            classByTypeinfo.put(entry.get("typeinfo").getAsLong(), entry.get("name").getAsString());
        }
        Map<String, Integer> depth = new HashMap<>();
        for (String name : byName.keySet()) {
            depthOf(name, byName, classByTypeinfo, depth);
        }
        // Which class each vtable pointer value belongs to, and which functions are a class's own
        // virtual functions (never its constructor).
        Map<Address, String> vptrs = new HashMap<>();
        for (JsonElement element : classes) {
            JsonObject entry = element.getAsJsonObject();
            for (JsonElement vtable : entry.getAsJsonArray("vtables")) {
                vptrs.put(base.add(vtable.getAsJsonObject().get("address").getAsLong() + 8),
                        entry.get("name").getAsString());
            }
        }
        java.util.Set<Address> virtuals = new java.util.HashSet<>();
        for (JsonElement element : functions) {
            virtuals.add(base.add(element.getAsJsonObject().get("address").getAsLong()));
        }

        // Candidates: functions referencing a vtable pointer that are not virtual functions.
        java.util.Set<Function> candidates = new java.util.LinkedHashSet<>();
        for (Address vptr : vptrs.keySet()) {
            for (ghidra.program.model.symbol.Reference ref : getReferencesTo(vptr)) {
                Function f = getFunctionContaining(ref.getFromAddress());
                if (f != null && !virtuals.contains(f.getEntryPoint())) {
                    candidates.add(f);
                }
            }
        }
        // A constructor stores its class's vtable pointer into its own object: *(this + 0), where
        // this is the first parameter. The last such store is the most derived class (a derived
        // constructor overwrites the pointer its inlined base constructor stored). Functions that
        // only store vtable pointers into other objects (factories, owners building members) are
        // not constructors of those classes.
        Map<Function, String> constructors = new HashMap<>();
        ghidra.app.decompiler.DecompInterface decompiler = new ghidra.app.decompiler.DecompInterface();
        decompiler.openProgram(currentProgram);
        monitor.initialize(candidates.size());
        monitor.setMessage("Finding constructors");
        for (Function f : candidates) {
            monitor.checkCancelled();
            monitor.incrementProgress(1);
            ghidra.program.model.pcode.HighFunction high =
                    decompiler.decompileFunction(f, 30, monitor).getHighFunction();
            if (high == null || high.getFunctionPrototype().getNumParams() == 0) {
                continue;
            }
            ghidra.program.model.pcode.HighVariable self =
                    high.getFunctionPrototype().getParam(0).getHighVariable();
            String last = null;
            long lastOrder = -1;
            java.util.Iterator<ghidra.program.model.pcode.PcodeOpAST> ops = high.getPcodeOps();
            while (ops.hasNext()) {
                ghidra.program.model.pcode.PcodeOpAST op = ops.next();
                if (op.getOpcode() != ghidra.program.model.pcode.PcodeOp.STORE) {
                    continue;
                }
                ghidra.program.model.pcode.Varnode target = op.getInput(1);
                // A typed `this` (void *, a struct) reaches the store through a cast or as
                // `this->vtable` (PTRSUB this, 0).
                for (int hop = 0; hop < 3 && target.getDef() != null; hop++) {
                    ghidra.program.model.pcode.PcodeOp def = target.getDef();
                    boolean cast = def.getOpcode() == ghidra.program.model.pcode.PcodeOp.CAST;
                    boolean field0 = (def.getOpcode() == ghidra.program.model.pcode.PcodeOp.PTRSUB
                            || def.getOpcode() == ghidra.program.model.pcode.PcodeOp.INT_ADD)
                            && def.getInput(1).isConstant() && def.getInput(1).getOffset() == 0;
                    if (!cast && !field0) {
                        break;
                    }
                    target = def.getInput(0);
                }
                if (self == null || target.getHigh() != self) {
                    continue;  // only *(this + 0): the pointer itself, not an offset from it
                }
                Long value = constantAddress(op.getInput(2), 6);
                String cls = value == null ? null : vptrs.get(toAddr(value));
                long order = op.getSeqnum().getTarget().getOffset() * 64 + op.getSeqnum().getTime();
                if (cls != null && order > lastOrder) {
                    last = cls;
                    lastOrder = order;
                }
            }
            if (last != null) {
                constructors.put(f, last);
            }
        }
        decompiler.dispose();
        // Undo constructor names an earlier run gave to functions that no longer qualify.
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (f.getSymbol().getSource() == SourceType.ANALYSIS && !constructors.containsKey(f) &&
                    f.getName().equals(f.getParentNamespace().getName()) && !virtuals.contains(f.getEntryPoint())) {
                try {
                    f.getSymbol().setNameAndNamespace(f.getSymbol().getName(), currentProgram.getGlobalNamespace(),
                            SourceType.ANALYSIS);
                    f.setName(null, SourceType.DEFAULT);
                } catch (Exception e) {
                    problems++;
                }
            }
        }
        int ctors = 0;
        for (Map.Entry<Function, String> entry : constructors.entrySet()) {
            String cls = entry.getValue();
            entry.getKey().addTag("lib:" + libraries.getOrDefault(cls, "game"));
            if (rename(entry.getKey(), cls, scopes(cls).get(scopes(cls).size() - 1))) {
                ctors++;
            }
        }
        // Destructors: the Itanium "deleting" destructor calls the "complete" destructor in the
        // slot before it and then operator_delete(this). That pair is usually slots 0 and 1, but a
        // class that declares its destructor after other virtual functions has it later (for
        // example CIsSystemStatic<T>, slots 9 and 10), so find the pair in each vtable by behaviour.
        Map<String, JsonObject> entryAt = new HashMap<>();
        for (JsonElement element : functions) {
            JsonObject entry = element.getAsJsonObject();
            entryAt.put(entry.get("address").getAsLong() + "/" + entry.get("offset").getAsLong(), entry);
        }
        java.util.Set<Address> deleters = new java.util.HashSet<>();
        for (Function f : getGlobalFunctions("operator_delete")) {
            deleters.add(f.getEntryPoint());
        }
        int dtors = 0;
        java.util.Set<Long> done = new java.util.HashSet<>();
        for (JsonElement element : classes) {
            for (JsonElement vt : element.getAsJsonObject().getAsJsonArray("vtables")) {
                JsonObject vtable = vt.getAsJsonObject();
                long offset = vtable.has("offset_to_top") ? -vtable.get("offset_to_top").getAsLong() : 0;
                if (offset != 0) {
                    continue;  // secondary vtables hold thunks to the primary destructors
                }
                JsonArray slots = vtable.getAsJsonArray("functions");
                for (int i = 1; i < slots.size(); i++) {
                    long complete = slots.get(i - 1).getAsLong();
                    long deleting = slots.get(i).getAsLong();
                    if (done.contains(deleting) || !isDeletingDestructor(base.add(deleting & ~1L),
                            base.add(complete & ~1L), deleters, i == 1)) {
                        continue;
                    }
                    done.add(deleting);
                    for (long[] pair : new long[][] {{complete, 0}, {deleting, 1}}) {
                        JsonObject entry = entryAt.get((pair[0] & ~1L) + "/0");
                        if (entry == null) {
                            continue;
                        }
                        String cls = entry.get("owner").getAsString();
                        String simple = scopes(cls).get(scopes(cls).size() - 1);
                        Function f = getFunctionAt(base.add(pair[0] & ~1L));
                        if (f != null && rename(f, cls, "~" + simple + (pair[1] == 1 ? "_deleting" : ""))) {
                            dtors++;
                        }
                    }
                    break;
                }
            }
        }
        return new int[] {ctors, dtors};
    }

    // A deleting destructor calls operator_delete and, unless the complete destructor is inlined
    // (then only trusted in slot 1, the usual place), the complete destructor itself.
    private boolean isDeletingDestructor(Address deleting, Address complete, java.util.Set<Address> deleters,
            boolean usualSlot) {
        Function f = getFunctionAt(deleting);
        if (f == null || deleters.isEmpty()) {
            return false;
        }
        boolean deletes = false;
        boolean callsComplete = false;
        for (ghidra.program.model.listing.Instruction ins : currentProgram.getListing().getInstructions(f.getBody(), true)) {
            for (Address target : ins.getFlows()) {
                Function callee = getFunctionAt(target);
                Address entry = callee == null ? target : (callee.isThunk() && callee.getThunkedFunction(true) != null
                        ? callee.getThunkedFunction(true).getEntryPoint() : callee.getEntryPoint());
                deletes |= deleters.contains(entry);
                callsComplete |= entry.equals(complete);
            }
        }
        return deletes && (callsComplete || usualSlot);
    }

    private Long constantAddress(ghidra.program.model.pcode.Varnode v, int depth) {
        if (v == null || depth == 0) {
            return null;
        }
        if (v.isConstant()) {
            return v.getOffset();
        }
        if (v.isAddress()) {
            ghidra.program.model.mem.MemoryBlock block = currentProgram.getMemory().getBlock(v.getAddress());
            if (block != null && block.isExecute()) {
                try {
                    return currentProgram.getMemory().getInt(v.getAddress()) & 0xffffffffL;
                } catch (Exception e) {
                    return null;
                }
            }
            return v.getOffset();
        }
        ghidra.program.model.pcode.PcodeOp def = v.getDef();
        if (def == null) {
            return null;
        }
        switch (def.getOpcode()) {
            case ghidra.program.model.pcode.PcodeOp.COPY:
            case ghidra.program.model.pcode.PcodeOp.CAST:
            case ghidra.program.model.pcode.PcodeOp.INDIRECT:
                return constantAddress(def.getInput(0), depth - 1);
            case ghidra.program.model.pcode.PcodeOp.PTRSUB:
            case ghidra.program.model.pcode.PcodeOp.INT_ADD: {
                Long a = constantAddress(def.getInput(0), depth - 1);
                Long b = constantAddress(def.getInput(1), depth - 1);
                return a != null && b != null ? (a + b) & 0xffffffffL : null;
            }
            default:
                return null;
        }
    }

    private int depthOf(String name, Map<String, JsonObject> byName, Map<Long, String> classByTypeinfo,
            Map<String, Integer> depth) {
        Integer known = depth.get(name);
        if (known != null) {
            return known;
        }
        depth.put(name, 0);
        int d = 0;
        JsonObject entry = byName.get(name);
        if (entry != null) {
            for (JsonElement b : entry.getAsJsonArray("bases")) {
                String baseName = classByTypeinfo.get(b.getAsJsonObject().get("typeinfo").getAsLong());
                if (baseName != null) {
                    d = Math.max(d, 1 + depthOf(baseName, byName, classByTypeinfo, depth));
                }
            }
        }
        depth.put(name, d);
        return d;
    }

    // Analysis-level rename that never touches a name a person (or the ELF import) set.
    private boolean rename(Function f, String cls, String name) {
        SourceType source = f.getSymbol().getSource();
        if (source == SourceType.USER_DEFINED || source == SourceType.IMPORTED) {
            return false;
        }
        Namespace ns = classNamespace(cls);
        if (ns == null) {
            return false;
        }
        try {
            f.getSymbol().setNameAndNamespace(
                    ghidra.program.model.symbol.SymbolUtilities.replaceInvalidChars(name, true), ns,
                    SourceType.ANALYSIS);
            return true;
        } catch (Exception e) {
            problems++;
            return false;
        }
    }

    // Splits "A::B<C::D>::E" into ["A", "B<C::D>", "E"] (only top-level "::" separate scopes).
    static List<String> scopes(String name) {
        List<String> parts = new ArrayList<>();
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

    private Namespace classNamespace(String name) {
        Namespace cached = namespaces.get(name);
        if (cached != null) {
            return cached;
        }
        Namespace parent = currentProgram.getGlobalNamespace();
        List<String> parts = scopes(name);
        try {
            for (int i = 0; i < parts.size(); i++) {
                String part = parts.get(i);
                Namespace existing = symbols.getNamespace(part, parent);
                if (existing == null) {
                    existing = i == parts.size() - 1
                            ? symbols.createClass(parent, part, SourceType.ANALYSIS)
                            : symbols.createNameSpace(parent, part, SourceType.ANALYSIS);
                }
                parent = existing;
            }
        } catch (Exception e) {
            problems++;
            return null;
        }
        namespaces.put(name, parent);
        return parent;
    }

    private void label(Address address, String name, Namespace ns) throws Exception {
        for (Symbol symbol : symbols.getSymbols(address)) {
            if (symbol.getName().equals(name) && symbol.getParentNamespace().equals(ns)) {
                return;
            }
        }
        symbols.createLabel(address, name, ns, SourceType.ANALYSIS);
    }

    // [offset to top][typeinfo *][function pointers...], only replacing undefined bytes.
    private void typeVtable(Address address, int count) {
        DataType pointer = PointerDataType.dataType;
        try {
            DataUtilities.createData(currentProgram, address, IntegerDataType.dataType, -1,
                    DataUtilities.ClearDataMode.CLEAR_ALL_UNDEFINED_CONFLICT_DATA);
            for (int i = 0; i <= count; i++) {
                DataUtilities.createData(currentProgram, address.add(4 + 4L * i), pointer, -1,
                        DataUtilities.ClearDataMode.CLEAR_ALL_UNDEFINED_CONFLICT_DATA);
            }
        } catch (Exception e) {
            // Something else is defined there already; the labels are enough.
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
}
