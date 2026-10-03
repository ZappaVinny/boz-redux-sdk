// Exports the studio engine's reflection data: every class registered with CIsClassInfo, its
// base classes (with their offsets) and its reflected fields (name, offset, size, flags, type).
//
// How the game registers a class (one registration function per class):
//   info = T::GetClassInfo();             // guarded static: CIsClassInfo(&s_info, "T")
//   CIsClassInfo::AddBase(info, baseInfo, offset);
//   spec = new CIsReflectPropertySpec<F>(spec, info, "m_field", offset, size, flags);
//   (often inlined: the 0x1c-byte spec is filled in place, +0 vtable, +4 info, +8 name,
//   +0xc name hash, +0x10 flags, +0x14 offset, +0x18 derived from size; flags 2 = network property)
//   CIsClassInfo::AddProperty(info, spec);
//
// Writes JSON (arg 1) and, with "structs" as arg 2, creates a structure per class (named after
// it, at the class's path, so Ghidra uses it for `this` in the class's __thiscall methods) with
// every reflected field, own and inherited, at its offset, sets __thiscall on the class's
// methods whose signature was never set, and names each class's
// T::GetClassInfo getter and T::RegisterReflection function (only where still unnamed). Structures
// and these names are rebuilt on each run (source ANALYSIS) and are not part of the exported
// symbol database.
// Run ApplyBozClasses first (it names the property-spec constructors).
// @category BOZ
// @menupath Tools.BOZ.Export Reflection

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.pcode.HighFunction;
import ghidra.program.model.pcode.PcodeOp;
import ghidra.program.model.pcode.PcodeOpAST;
import ghidra.program.model.pcode.Varnode;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.io.FileWriter;
import java.util.*;

public class ExportBozReflection extends GhidraScript {
    private static final long CLASSINFO_CTOR = 0x4a04f5f4L;
    private static final long ADD_BASE = 0x4a04f4eeL;
    private static final long ADD_PROPERTY = 0x4a04f2b8L;
    private static final String SPEC = "CIsReflectPropertySpec<";

    private static class Field {
        String name, type;
        long offset, size, flags;
    }

    private static class Info {
        String name;
        Address global;
        Function getter;
        final List<long[]> baseRefs = new ArrayList<>();  // {base info global, offset}
        final List<Field> fields = new ArrayList<>();
        final Set<String> registeredIn = new TreeSet<>();
        final Set<Address> registrars = new TreeSet<>();
    }

    private DecompInterface decompiler;
    private final Map<Address, Info> byGlobal = new HashMap<>();
    private final Map<Address, Info> byGetter = new HashMap<>();

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File out = args.length > 0 ? new File(args[0]) : askFile("Write reflection JSON", "Export");
        boolean structs = args.length > 1 && args[1].equals("structs");
        decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);

        // 1. Class records: each CIsClassInfo constructor call names a static info global.
        for (Function caller : callersOf(toAddr(CLASSINFO_CTOR))) {
            for (PcodeOpAST op : calls(caller, toAddr(CLASSINFO_CTOR))) {
                Long global = constant(op.getInput(1), 8);
                String name = string(op.getInput(2));
                if (global == null || name == null) {
                    continue;
                }
                Info info = byGlobal.computeIfAbsent(toAddr(global), a -> new Info());
                info.name = name;
                info.global = toAddr(global);
                if (caller.getBody().getNumAddresses() < 80) {
                    info.getter = caller;  // small guarded getter returning the global
                    byGetter.put(caller.getEntryPoint(), info);
                }
            }
        }

        // 2. Properties and bases, from every function calling a property-spec constructor or AddBase.
        Set<Address> specCtors = new HashSet<>();
        Map<Address, String> specType = new HashMap<>();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            String ns = f.getParentNamespace().getName();
            if (ns.startsWith(SPEC) && f.getName().equals(ns)) {
                specCtors.add(f.getEntryPoint());
                specType.put(f.getEntryPoint(), ns.substring(SPEC.length(), ns.length() - 1));
            }
        }
        Set<Function> registrars = new LinkedHashSet<>();
        for (Address ctor : specCtors) {
            registrars.addAll(callersOf(ctor));
        }
        registrars.addAll(callersOf(toAddr(ADD_BASE)));
        registrars.addAll(callersOf(toAddr(ADD_PROPERTY)));
        // Give every property-spec constructor its real signature (spec, info, name, offset, size,
        // flags) so the decompiler passes the two stack arguments.
        int fixed = 0;
        for (Function f : registrars) {
            for (ghidra.program.model.listing.Instruction ins : currentProgram.getListing().getInstructions(f.getBody(), true)) {
                if (!ins.getFlowType().isCall()) {
                    continue;
                }
                for (Address target : ins.getFlows()) {
                    Function ctor = getFunctionAt(target);
                    if (ctor != null && ctor.getParameterCount() != 6 && specTypeOf(target, specType) != null) {
                        setSpecSignature(ctor);
                        fixed++;
                    }
                }
            }
        }
        if (fixed > 0) {
            println("ExportBozReflection: set the 6-argument signature on " + fixed + " property-spec constructors");
        }
        int unresolved = 0;
        for (Function f : registrars) {
            monitor.checkCancelled();
            HighFunction high = decompile(f);
            if (high == null) {
                continue;
            }
            for (Iterator<PcodeOpAST> it = high.getPcodeOps(); it.hasNext();) {
                PcodeOpAST op = it.next();
                if (op.getOpcode() != PcodeOp.CALL) {
                    continue;
                }
                Address target = op.getInput(0).getAddress();
                if (target.getOffset() == ADD_BASE && op.getNumInputs() >= 4) {
                    Info derived = infoOf(op.getInput(1));
                    Info base = infoOf(op.getInput(2));
                    Long offset = constant(op.getInput(3), 4);
                    if (derived != null && base != null && derived != base) {
                        derived.baseRefs.add(new long[] {base.global.getOffset(), offset == null ? 0 : offset});
                        derived.registeredIn.add(f.getName(true));
                        derived.registrars.add(f.getEntryPoint());
                    }
                } else if (target.getOffset() == ADD_PROPERTY && op.getNumInputs() >= 3) {
                    Field field = inlineSpec(high, op.getInput(2));
                    Info owner = infoOf(op.getInput(1));
                    if (field != null && owner != null) {
                        addField(owner, field);
                        owner.registeredIn.add(f.getName(true));
                    owner.registrars.add(f.getEntryPoint());
                    } else if (!viaCtor(high, op.getInput(2), specType)) {
                        unresolved++;
                        if (missed.size() < 12) {
                            missed.add(f.getName(true) + "@" + op.getSeqnum().getTarget() + (owner == null ? " no-owner" : " no-spec"));
                        }
                    }
                } else if (op.getNumInputs() >= 7 && specTypeOf(target, specType) != null) {
                    Info owner = infoOf(op.getInput(2));
                    String name = string(op.getInput(3));
                    Long offset = constant(op.getInput(4), 4);
                    Long size = constant(op.getInput(5), 4);
                    Long flags = constant(op.getInput(6), 4);
                    if (owner == null || name == null || offset == null) {
                        unresolved++;
                        continue;
                    }
                    Field field = new Field();
                    field.name = name;
                    field.type = specTypeOf(target, specType);
                    field.offset = offset;
                    field.size = size == null ? 0 : size;
                    field.flags = flags == null ? 0 : flags;
                    addField(owner, field);
                    owner.registeredIn.add(f.getName(true));
                    owner.registrars.add(f.getEntryPoint());
                }
            }
        }
        decompiler.dispose();

        // 3. JSON.
        List<Info> infos = new ArrayList<>(byGlobal.values());
        infos.sort(Comparator.comparing(i -> i.name));
        JsonArray classes = new JsonArray();
        int fieldCount = 0;
        for (Info info : infos) {
            info.fields.sort(Comparator.comparingLong(x -> x.offset));
            JsonObject c = new JsonObject();
            c.addProperty("name", info.name);
            c.addProperty("class_info", info.global.toString());
            if (info.getter != null) {
                c.addProperty("get_class_info", info.getter.getEntryPoint().toString());
            }
            JsonArray bases = new JsonArray();
            for (long[] b : info.baseRefs) {
                JsonObject base = new JsonObject();
                base.addProperty("name", byGlobal.get(toAddr(b[0])).name);
                base.addProperty("offset", b[1]);
                bases.add(base);
            }
            c.add("bases", bases);
            JsonArray fields = new JsonArray();
            for (Field x : info.fields) {
                JsonObject field = new JsonObject();
                field.addProperty("name", x.name);
                field.addProperty("offset", x.offset);
                field.addProperty("size", x.size);
                field.addProperty("flags", x.flags);
                field.addProperty("type", x.type);
                fields.add(field);
                fieldCount++;
            }
            c.add("fields", fields);
            JsonArray reg = new JsonArray();
            info.registeredIn.forEach(reg::add);
            c.add("registered_in", reg);
            classes.add(c);
        }
        JsonObject report = new JsonObject();
        report.add("classes", classes);
        try (FileWriter writer = new FileWriter(out)) {
            new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create().toJson(report, writer);
        }

        for (String m : missed) {
            println("unresolved: " + m);
        }
        int made = structs ? makeStructs(infos) : 0;
        int named = structs ? nameFunctions(infos) : 0;
        println(String.format("ExportBozReflection: %d classes, %d fields (%d registered twice, %d unresolved), %d named property types, %d structs, %d functions named -> %s",
                infos.size(), fieldCount, duplicates, unresolved, specCtors.size(), made, named, out));
    }

    private final List<String> missed = new ArrayList<>();

    private void setSpecSignature(Function ctor) throws Exception {
        DataType ptr = new PointerDataType(VoidDataType.dataType);
        String[] names = {"spec", "info", "name", "offset", "size", "flags"};
        DataType[] types = {ptr, ptr, new PointerDataType(CharDataType.dataType), IntegerDataType.dataType,
                IntegerDataType.dataType, IntegerDataType.dataType};
        List<ghidra.program.model.listing.Parameter> params = new ArrayList<>();
        for (int i = 0; i < names.length; i++) {
            params.add(new ghidra.program.model.listing.ParameterImpl(names[i], types[i], currentProgram));
        }
        ctor.replaceParameters(params, Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, true,
                ghidra.program.model.symbol.SourceType.ANALYSIS);
    }

    // True when the spec passed to AddProperty was built by a (named or vtable-identified) constructor call.
    private boolean viaCtor(HighFunction high, Varnode spec, Map<Address, String> named) {
        if (spec == null || spec.getHigh() == null) {
            return false;
        }
        for (Iterator<PcodeOpAST> it = high.getPcodeOps(); it.hasNext();) {
            PcodeOpAST op = it.next();
            if (op.getOpcode() == PcodeOp.CALL && op.getNumInputs() > 1 && op.getInput(1).getHigh() == spec.getHigh()
                    && specTypeOf(op.getInput(0).getAddress(), named) != null) {
                return true;
            }
        }
        return false;
    }

    private int duplicates = 0;

    private void addField(Info owner, Field field) {
        for (Field x : owner.fields) {
            if (x.offset == field.offset && x.name.equals(field.name)) {
                duplicates++;
                return;
            }
        }
        owner.fields.add(field);
    }

    // A property spec filled in place (inlined constructor): the stores into the spec's memory.
    private Field inlineSpec(HighFunction high, Varnode spec) {
        if (spec == null || spec.getHigh() == null) {
            return null;
        }
        ghidra.program.model.pcode.HighVariable target = spec.getHigh();
        Map<Long, Varnode> stored = new HashMap<>();
        for (Iterator<PcodeOpAST> it = high.getPcodeOps(); it.hasNext();) {
            PcodeOpAST op = it.next();
            if (op.getOpcode() != PcodeOp.STORE) {
                continue;
            }
            Varnode addr = op.getInput(1);
            long off = 0;
            PcodeOp def = addr.getDef();
            if (def != null && (def.getOpcode() == PcodeOp.PTRSUB || def.getOpcode() == PcodeOp.INT_ADD)
                    && def.getInput(1).isConstant()) {
                off = def.getInput(1).getOffset();
                addr = def.getInput(0);
            } else if (def != null && def.getOpcode() == PcodeOp.PTRADD && def.getInput(1).isConstant()
                    && def.getInput(2).isConstant()) {
                off = def.getInput(1).getOffset() * def.getInput(2).getOffset();
                addr = def.getInput(0);
            }
            if (addr.getHigh() == target) {
                stored.putIfAbsent(off, op.getInput(2));
            }
        }
        Long vtable = constant(stored.get(0L), 6);
        String type = vtable == null ? null : vtableSpec(toAddr(vtable));
        String name = string(stored.get(8L));
        Long offset = constant(stored.get(0x14L), 6);
        if (type == null || name == null || offset == null) {
            return null;
        }
        Field field = new Field();
        field.name = name;
        field.type = type;
        field.offset = offset;
        Long flags = constant(stored.get(0x10L), 6);
        field.flags = flags == null ? 0 : flags;
        // +0x18 is computed from the size: f(size, unit); take the size argument.
        Varnode derived = stored.get(0x18L);
        PcodeOp sizeCall = derived == null ? null : derived.getDef();
        Long size = sizeCall != null && sizeCall.getOpcode() == PcodeOp.CALL && sizeCall.getNumInputs() > 1
                ? constant(sizeCall.getInput(1), 4) : null;
        field.size = size == null ? 0 : size;
        return field;
    }

    // The property type a constructor builds: from its name, or from the CIsReflectPropertySpec<T>
    // vtable it stores (constructors the class map could not name). Cached; "" means not a spec.
    private final Map<Address, String> specCache = new HashMap<>();

    private String specTypeOf(Address ctor, Map<Address, String> named) {
        if (named.containsKey(ctor)) {
            return named.get(ctor);
        }
        String cached = specCache.get(ctor);
        if (cached == null) {
            cached = "";
            Function f = getFunctionAt(ctor);
            if (f != null && f.getBody().getNumAddresses() < 200) {
                for (ghidra.program.model.listing.Instruction ins : currentProgram.getListing().getInstructions(f.getBody(), true)) {
                    for (Reference r : ins.getReferencesFrom()) {
                        String t = vtableSpec(r.getToAddress());
                        if (t == null) {
                            try {
                                t = vtableSpec(toAddr(currentProgram.getMemory().getInt(r.getToAddress()) & 0xffffffffL));
                            } catch (Exception e) {
                                t = null;
                            }
                        }
                        if (t != null) {
                            cached = t;
                        }
                    }
                }
            }
            specCache.put(ctor, cached);
        }
        return cached.isEmpty() ? null : cached;
    }

    // "T" when address is (inside the first words of) a CIsReflectPropertySpec<T> vtable.
    private String vtableSpec(Address a) {
        for (int back = 0; back <= 8; back += 4) {
            if (a.getOffset() < back) {
                break;
            }
            for (ghidra.program.model.symbol.Symbol s : currentProgram.getSymbolTable().getSymbols(a.subtract(back))) {
                String ns = s.getParentNamespace().getName();
                if (s.getName().startsWith("vtable") && ns.startsWith(SPEC)) {
                    return ns.substring(SPEC.length(), ns.length() - 1);
                }
            }
        }
        return null;
    }

    private int nameFunctions(List<Info> infos) throws Exception {
        int named = 0;
        for (Info info : infos) {
            ghidra.program.model.symbol.Namespace ns = getNamespace(null,
                    ghidra.program.model.symbol.SymbolUtilities.replaceInvalidChars(info.name.replace(", ", ","), true));
            if (ns == null) {
                ns = currentProgram.getSymbolTable().createClass(currentProgram.getGlobalNamespace(),
                        ghidra.program.model.symbol.SymbolUtilities.replaceInvalidChars(info.name.replace(", ", ","), true),
                        ghidra.program.model.symbol.SourceType.ANALYSIS);
            }
            if (info.getter != null && info.getter.getSymbol().getSource() == ghidra.program.model.symbol.SourceType.DEFAULT) {
                info.getter.getSymbol().setNameAndNamespace("GetClassInfo", ns, ghidra.program.model.symbol.SourceType.ANALYSIS);
                named++;
            }
            for (Address reg : info.registrars) {
                Function f = currentProgram.getFunctionManager().getFunctionAt(reg);
                if (f != null && f.getSymbol().getSource() == ghidra.program.model.symbol.SourceType.DEFAULT) {
                    try {
                        f.getSymbol().setNameAndNamespace("RegisterReflection", ns, ghidra.program.model.symbol.SourceType.ANALYSIS);
                        named++;
                    } catch (Exception e) {
                        // second registrar for the same class (registered twice): keep its default name
                    }
                }
            }
            if (currentProgram.getSymbolTable().getSymbols(info.global).length == 0
                    || currentProgram.getSymbolTable().getPrimarySymbol(info.global).getSource() == ghidra.program.model.symbol.SourceType.DEFAULT) {
                currentProgram.getSymbolTable().createLabel(info.global, "s_classInfo", ns, ghidra.program.model.symbol.SourceType.ANALYSIS);
            }
        }
        return named;
    }

    // Every field, own and inherited, with its offset in the full object.
    private void flatten(Info info, long base, Map<Long, Field> out, Set<Info> seen) {
        if (!seen.add(info)) {
            return;
        }
        for (long[] b : info.baseRefs) {
            flatten(byGlobal.get(toAddr(b[0])), base + b[1], out, seen);
        }
        for (Field x : info.fields) {
            Field copy = new Field();
            copy.name = x.name;
            copy.type = x.type;
            copy.size = x.size;
            copy.flags = x.flags;
            copy.offset = base + x.offset;
            out.put(copy.offset, copy);
        }
    }

    // One structure per class, named after it and placed at the class's own path (root for
    // top-level classes), which is where Ghidra looks for the type of `this` in a __thiscall
    // method. Methods of the class get __thiscall where their signature was never set.
    private int makeStructs(List<Info> infos) throws Exception {
        DataTypeManager dtm = currentProgram.getDataTypeManager();
        Category old = dtm.getCategory(new CategoryPath("/BOZReflect"));
        if (old != null) {
            dtm.getRootCategory().removeCategory("BOZReflect", monitor);  // earlier layout
        }
        int made = 0;
        int methods = 0;
        for (Info info : infos) {
            Map<Long, Field> all = new TreeMap<>();
            flatten(info, 0, all, new HashSet<>());
            if (all.isEmpty()) {
                continue;
            }
            long end = 4;
            for (Field x : all.values()) {
                end = Math.max(end, x.offset + Math.max(1, x.size));
            }
            List<String> parts = new ArrayList<>();
            for (String p : info.name.replace(", ", ",").split("::")) {
                parts.add(ghidra.program.model.symbol.SymbolUtilities.replaceInvalidChars(p, true));
            }
            String name = parts.remove(parts.size() - 1);
            CategoryPath category = CategoryPath.ROOT;
            for (String p : parts) {
                category = new CategoryPath(category, p);
            }
            StructureDataType s = new StructureDataType(category, name, (int) ((end + 3) & ~3L), dtm);
            if (!all.containsKey(0L)) {
                s.replaceAtOffset(0, new PointerDataType(VoidDataType.dataType), 4, "vtable", "vtable pointer");
            }
            for (Field x : all.values()) {
                DataType t = typeOf(x);
                try {
                    s.replaceAtOffset((int) x.offset, t, t.getLength(), x.name, x.type);
                } catch (Exception e) {
                    // overlapping field (unions, packed bitsets): keep the first
                }
            }
            // Hand-made fields from the symbol database (/BOZ/<class>) fill the gaps.
            DataType db = dtm.getDataType(new CategoryPath("/BOZ"), name);
            if (db instanceof Structure) {
                Structure from = (Structure) db;
                if (s.getLength() < from.getLength()) {
                    s.growStructure(from.getLength() - s.getLength());
                }
                for (DataTypeComponent c : from.getDefinedComponents()) {
                    boolean free = true;
                    for (int i = 0; i < c.getLength() && free; i++) {
                        DataTypeComponent at = s.getComponentContaining(c.getOffset() + i);
                        free = at == null || at.getDataType() == DataType.DEFAULT;
                    }
                    if (free) {
                        try {
                            s.replaceAtOffset(c.getOffset(), c.getDataType(), c.getLength(), c.getFieldName(), c.getComment());
                        } catch (IllegalArgumentException e) {
                            // keep the reflected layout
                        }
                    }
                }
            }
            dtm.addDataType(s, DataTypeConflictHandler.REPLACE_HANDLER);
            made++;
            methods += useThisCall(info.name);
        }
        println("ExportBozReflection: __thiscall set on " + methods + " methods");
        return made;
    }

    private int useThisCall(String className) throws Exception {
        ghidra.program.model.symbol.Namespace ns = getNamespace(null,
                ghidra.program.model.symbol.SymbolUtilities.replaceInvalidChars(className.replace(", ", ","), true));
        if (ns == null) {
            return 0;
        }
        int n = 0;
        for (ghidra.program.model.symbol.Symbol sym : currentProgram.getSymbolTable().getSymbols(ns)) {
            if (sym.getSymbolType() != ghidra.program.model.symbol.SymbolType.FUNCTION) {
                continue;
            }
            Function f = (Function) sym.getObject();
            String fn = f.getName();
            // Static helpers take no object.
            if (fn.equals("GetClassInfo") || fn.equals("RegisterReflection") || fn.equals("FromEntity")
                    || f.getSignatureSource() != ghidra.program.model.symbol.SourceType.DEFAULT
                    || "__thiscall".equals(f.getCallingConventionName())) {
                continue;
            }
            f.setCallingConvention("__thiscall");
            n++;
        }
        return n;
    }

    private DataType typeOf(Field x) {
        DataType base;
        switch (x.type.replace('_', ' ')) {
            case "float": base = FloatDataType.dataType; break;
            case "int": base = IntegerDataType.dataType; break;
            case "unsigned int": base = UnsignedIntegerDataType.dataType; break;
            case "short": base = ShortDataType.dataType; break;
            case "char": base = CharDataType.dataType; break;
            case "unsigned char": base = ByteDataType.dataType; break;
            case "bool": base = BooleanDataType.dataType; break;
            default: base = null;
        }
        long size = Math.max(1, x.size);
        if (base != null && base.getLength() == size) {
            return base;
        }
        return new ArrayDataType(Undefined1DataType.dataType, (int) size, 1);
    }

    // The info a varnode refers to: a getter call result or the info global itself.
    private Info infoOf(Varnode v) {
        for (int depth = 0; v != null && depth < 6; depth++) {
            Long c = constant(v, 6);
            if (c != null) {
                return byGlobal.get(toAddr(c));
            }
            PcodeOp def = v.getDef();
            if (def == null) {
                return null;
            }
            if (def.getOpcode() == PcodeOp.CALL) {
                return byGetter.get(def.getInput(0).getAddress());
            }
            if (def.getOpcode() == PcodeOp.COPY || def.getOpcode() == PcodeOp.CAST
                    || def.getOpcode() == PcodeOp.INDIRECT || def.getOpcode() == PcodeOp.MULTIEQUAL) {
                v = def.getInput(0);
            } else {
                return null;
            }
        }
        return null;
    }

    private Set<Function> callersOf(Address target) {
        Set<Function> out = new LinkedHashSet<>();
        for (Reference r : getReferencesTo(target)) {
            Function f = getFunctionContaining(r.getFromAddress());
            if (r.getReferenceType().isCall() && f != null) {
                out.add(f);
            }
        }
        return out;
    }

    private List<PcodeOpAST> calls(Function f, Address target) {
        List<PcodeOpAST> out = new ArrayList<>();
        HighFunction high = decompile(f);
        if (high == null) {
            return out;
        }
        for (Iterator<PcodeOpAST> it = high.getPcodeOps(); it.hasNext();) {
            PcodeOpAST op = it.next();
            if (op.getOpcode() == PcodeOp.CALL && op.getInput(0).getAddress().equals(target) && op.getNumInputs() >= 3) {
                out.add(op);
            }
        }
        return out;
    }

    private HighFunction decompile(Function f) {
        DecompileResults r = decompiler.decompileFunction(f, 30, monitor);
        return r == null ? null : r.getHighFunction();
    }

    private String string(Varnode v) {
        Long addr = constant(v, 6);
        if (addr == null) {
            return null;
        }
        try {
            StringBuilder sb = new StringBuilder();
            Address a = toAddr(addr);
            for (int i = 0; i < 256; i++) {
                byte b = currentProgram.getMemory().getByte(a.add(i));
                if (b == 0) {
                    break;
                }
                if (b < 0x20 || b > 0x7e) {
                    return null;
                }
                sb.append((char) b);
            }
            return sb.length() == 0 ? null : sb.toString();
        } catch (Exception e) {
            return null;
        }
    }

    private Long constant(Varnode v, int depth) {
        if (v == null || depth == 0) {
            return null;
        }
        if (v.isConstant()) {
            return v.getOffset();
        }
        if (v.isAddress()) {
            MemoryBlock block = currentProgram.getMemory().getBlock(v.getAddress());
            if (block != null && block.isExecute()) {
                try {
                    return currentProgram.getMemory().getInt(v.getAddress()) & 0xffffffffL;
                } catch (Exception e) {
                    return null;
                }
            }
            return v.getOffset();
        }
        PcodeOp def = v.getDef();
        if (def == null) {
            return null;
        }
        switch (def.getOpcode()) {
            case PcodeOp.COPY:
            case PcodeOp.CAST:
            case PcodeOp.INDIRECT:
                return constant(def.getInput(0), depth - 1);
            case PcodeOp.PTRSUB:
            case PcodeOp.INT_ADD: {
                Long a = constant(def.getInput(0), depth - 1);
                Long b = constant(def.getInput(1), depth - 1);
                return a != null && b != null ? (a + b) & 0xffffffffL : null;
            }
            default:
                return null;
        }
    }
}
