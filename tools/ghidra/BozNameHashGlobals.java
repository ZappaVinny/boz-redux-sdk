// Names the globals that hold string hashes. The game identifies events, entity names, sounds and
// types by IwHashString(name), and caches many of those hashes in globals filled at start-up
// (`g = IwHashString("EVENT_ROUND_START")`). Code then reads `*g`, which says nothing until the
// global is named. Observer subject ids work the same way through SubjectId_Register (the hash
// of a SUBJECT_* name). This labels each such global hash_<string> (source ANALYSIS: rebuilt, not
// exported) and writes the full list (global, string, hash value, writer) as JSON.
// Args: output JSON path.
// @category BOZ
// @menupath Tools.BOZ.Name Hash Globals

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.pcode.HighFunction;
import ghidra.program.model.pcode.PcodeOp;
import ghidra.program.model.pcode.PcodeOpAST;
import ghidra.program.model.pcode.Varnode;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolUtilities;

import java.io.File;
import java.io.FileWriter;
import java.util.*;

public class BozNameHashGlobals extends GhidraScript {
    private static final long IW_HASH_STRING = 0x4a24ba2cL;
    // Subject (observer event) ids: SubjectId_Register(registry, std::string name) returns
    // IwHashString(name); the string is built just before by the std::string constructor.
    private static final long SUBJECT_REGISTER = 0x4a0bd312L;
    private static final long STRING_CTOR = 0x4a019d04L;

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File out = args.length > 0 ? new File(args[0]) : askFile("Write hash globals JSON", "Export");
        Address hashFn = toAddr(IW_HASH_STRING);
        Set<Function> callers = new LinkedHashSet<>();
        for (Address target : new Address[] {hashFn, toAddr(SUBJECT_REGISTER)}) {
            for (Reference r : getReferencesTo(target)) {
                Function f = getFunctionContaining(r.getFromAddress());
                if (f != null && r.getReferenceType().isCall()) {
                    callers.add(f);
                }
            }
        }
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        Map<Address, String> found = new TreeMap<>();
        Map<Address, String> writer = new HashMap<>();
        Set<Address> conflicting = new HashSet<>();
        monitor.initialize(callers.size());
        for (Function f : callers) {
            monitor.checkCancelled();
            monitor.incrementProgress(1);
            DecompileResults r = decompiler.decompileFunction(f, 30, monitor);
            HighFunction high = r == null ? null : r.getHighFunction();
            if (high == null) {
                continue;
            }
            List<PcodeOpAST> ops = new ArrayList<>();
            high.getPcodeOps().forEachRemaining(ops::add);
            ops.sort(Comparator.comparing(PcodeOpAST::getSeqnum));
            Map<Long, String> strings = new HashMap<>();  // std::string on the stack -> text
            for (PcodeOpAST op : ops) {
                if (op.getOpcode() != PcodeOp.CALL || op.getNumInputs() < 2) {
                    continue;
                }
                long callee = op.getInput(0).getAddress().getOffset();
                if (callee == STRING_CTOR && op.getNumInputs() >= 3) {
                    Long slot = stackSlot(op.getInput(1));
                    String text = string(op.getInput(2));
                    if (slot != null && text != null) {
                        strings.put(slot, text);
                    }
                    continue;
                }
                String text;
                if (callee == SUBJECT_REGISTER && op.getNumInputs() >= 3) {
                    Long slot = stackSlot(op.getInput(2));
                    text = slot == null ? null : strings.get(slot);
                } else if (callee == IW_HASH_STRING) {
                    text = string(op.getInput(1));
                } else {
                    continue;
                }
                if (op.getOutput() == null) {
                    continue;
                }
                if (text == null) {
                    continue;
                }
                // Where the result goes: a STORE of it to a constant data address.
                for (Iterator<PcodeOp> uses = op.getOutput().getDescendants(); uses.hasNext();) {
                    PcodeOp use = uses.next();
                    Varnode value = use.getOpcode() == PcodeOp.STORE ? use.getInput(2) : null;
                    if (use.getOpcode() == PcodeOp.COPY && use.getOutput() != null && use.getOutput().isAddress()) {
                        record(use.getOutput().getAddress(), text, f, found, writer, conflicting);
                        continue;
                    }
                    if (value == null) {
                        continue;
                    }
                    Long a = constant(use.getInput(1), 6);
                    if (a != null) {
                        record(toAddr(a), text, f, found, writer, conflicting);
                    }
                }
            }
        }
        decompiler.dispose();

        int labelled = 0;
        JsonArray list = new JsonArray();
        for (Map.Entry<Address, String> e : found.entrySet()) {
            if (conflicting.contains(e.getKey())) {
                continue;
            }
            MemoryBlock block = currentProgram.getMemory().getBlock(e.getKey());
            if (block == null || block.isExecute()) {
                continue;
            }
            String label = "hash_" + SymbolUtilities.replaceInvalidChars(e.getValue(), true);
            if (label.length() > 120) {
                label = label.substring(0, 120);
            }
            boolean named = false;
            for (Symbol s : currentProgram.getSymbolTable().getSymbols(e.getKey())) {
                named |= s.getSource() == SourceType.USER_DEFINED || s.getSource() == SourceType.IMPORTED
                        || s.getName().equals(label);
            }
            if (!named) {
                currentProgram.getSymbolTable().createLabel(e.getKey(), label, SourceType.ANALYSIS);
                labelled++;
            }
            JsonObject item = new JsonObject();
            item.addProperty("global", e.getKey().toString());
            item.addProperty("string", e.getValue());
            item.addProperty("hash", String.format("0x%08x", iwHash(e.getValue())));
            item.addProperty("written_by", writer.get(e.getKey()));
            list.add(item);
        }
        JsonObject report = new JsonObject();
        report.add("hash_globals", list);
        try (FileWriter w = new FileWriter(out)) {
            new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create().toJson(report, w);
        }
        println(String.format("BozNameHashGlobals: %d functions hash strings, %d hash globals (%d labelled, %d with conflicting strings skipped) -> %s",
                callers.size(), list.size(), labelled, conflicting.size(), out));
    }

    private void record(Address a, String text, Function f, Map<Address, String> found, Map<Address, String> writer,
            Set<Address> conflicting) {
        String prev = found.putIfAbsent(a, text);
        if (prev != null && !prev.equals(text)) {
            conflicting.add(a);
        }
        writer.putIfAbsent(a, f.getName(true));
    }

    // IwHashString (image 0x24ba2c): h = 5381; for each byte, A-Z lowercased, h = h * 33 + c.
    private static long iwHash(String s) {
        long h = 5381;
        for (char c : s.toLowerCase().toCharArray()) {
            h = ((h * 33) + c) & 0xffffffffL;
        }
        return h;
    }

    private String string(Varnode v) {
        Long addr = constant(v, 6);
        if (addr == null) {
            return null;
        }
        try {
            StringBuilder sb = new StringBuilder();
            Address a = toAddr(addr);
            for (int i = 0; i < 200; i++) {
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

    // Stack offset of a pointer to a local (PTRSUB sp, off), or null.
    private Long stackSlot(Varnode v) {
        for (int i = 0; v != null && i < 4; i++) {
            PcodeOp def = v.getDef();
            if (def == null) {
                return null;
            }
            if (def.getOpcode() == PcodeOp.PTRSUB && def.getInput(0).isRegister() && def.getInput(1).isConstant()) {
                return def.getInput(1).getOffset();
            }
            if (def.getOpcode() == PcodeOp.PTRSUB && def.getInput(0).isConstant() && def.getInput(0).getOffset() == 0
                    && def.getInput(1).isConstant()) {
                return def.getInput(1).getOffset();  // stack-space reference
            }
            if (def.getOpcode() != PcodeOp.COPY && def.getOpcode() != PcodeOp.CAST) {
                return null;
            }
            v = def.getInput(0);
        }
        return null;
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
