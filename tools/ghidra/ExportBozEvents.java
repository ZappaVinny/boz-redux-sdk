// Maps the game's observer event bus: for every SUBJECT_* event (ids named hash_SUBJECT_* by
// BozNameHashGlobals), which functions send it (CIsSubject::NotifyVirtual / Dispatch,
// CIsNetworkSubject::Notify / Dispatch), which subscribe to it (CIsSubject::Subscribe /
// Unsubscribe), and which handle it (OnEvent methods comparing the id).
// Args: output JSON path, then optionally "annotate" to put a repeatable comment on each function
// listing the events it sends, subscribes to and handles (rebuilt each run; plate and EOL comments
// are left alone). Run BozNameHashGlobals and BozTypeGotPointers first.
// @category BOZ
// @menupath Tools.BOZ.Export Events

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
import ghidra.program.model.symbol.Symbol;

import java.io.File;
import java.io.FileWriter;
import java.util.*;

public class ExportBozEvents extends GhidraScript {
    // API function name -> (role, index of the event id among the call's inputs)
    private static final Object[][] API = {
        {"CIsSubject::Subscribe", "subscribes", 3},
        {"CIsSubject::Unsubscribe", "unsubscribes", 3},
        {"CIsSubject::NotifyVirtual", "sends", 2},
        {"CIsSubject::Dispatch", "sends", 2},
        {"CIsNetworkSubject::Notify", "sends", 2},
        {"CIsNetworkSubject::Dispatch", "sends", 2},
    };

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File out = args.length > 0 ? new File(args[0]) : askFile("Write events JSON", "Export");
        Map<Address, Object[]> api = new HashMap<>();
        for (Object[] a : API) {
            for (Function f : functionsNamed((String) a[0])) {
                api.put(f.getEntryPoint(), a);
            }
        }
        Set<Function> work = new LinkedHashSet<>();
        for (Address a : api.keySet()) {
            for (Reference r : getReferencesTo(a)) {
                Function f = getFunctionContaining(r.getFromAddress());
                if (f != null && r.getReferenceType().isCall()) {
                    work.add(f);
                }
            }
        }
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (f.getName().startsWith("OnEvent")) {
                work.add(f);
            }
        }

        // event -> role -> functions
        Map<String, Map<String, Set<String>>> events = new TreeMap<>();
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        monitor.initialize(work.size());
        for (Function f : work) {
            monitor.checkCancelled();
            monitor.incrementProgress(1);
            DecompileResults r = decompiler.decompileFunction(f, 30, monitor);
            HighFunction high = r == null ? null : r.getHighFunction();
            if (high == null) {
                continue;
            }
            Set<String> classified = new HashSet<>();
            for (Iterator<PcodeOpAST> it = high.getPcodeOps(); it.hasNext();) {
                PcodeOpAST op = it.next();
                if (op.getOpcode() != PcodeOp.CALL) {
                    continue;
                }
                Object[] a = api.get(op.getInput(0).getAddress());
                int index = a == null ? -1 : (Integer) a[2];
                if (a == null || op.getNumInputs() <= index) {
                    continue;
                }
                String ev = eventOf(op.getInput(index));
                if (ev != null) {
                    add(events, ev, (String) a[1], f);
                    classified.add(ev);
                }
            }
            if (f.getName().startsWith("OnEvent")) {
                for (Iterator<PcodeOpAST> it = high.getPcodeOps(); it.hasNext();) {
                    PcodeOpAST op = it.next();
                    if (op.getOpcode() == PcodeOp.LOAD) {
                        String ev = eventAt(op.getInput(1));
                        if (ev != null && !classified.contains(ev)) {
                            add(events, ev, "handles", f);
                        }
                    }
                }
            }
        }
        decompiler.dispose();

        if (args.length > 1 && args[1].equals("annotate")) {
            annotate(events);
        }
        JsonArray list = new JsonArray();
        for (Map.Entry<String, Map<String, Set<String>>> e : events.entrySet()) {
            JsonObject item = new JsonObject();
            item.addProperty("event", e.getKey());
            for (Map.Entry<String, Set<String>> role : e.getValue().entrySet()) {
                JsonArray fs = new JsonArray();
                role.getValue().forEach(fs::add);
                item.add(role.getKey(), fs);
            }
            list.add(item);
        }
        JsonObject report = new JsonObject();
        report.add("events", list);
        try (FileWriter w = new FileWriter(out)) {
            new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create().toJson(report, w);
        }
        println(String.format("ExportBozEvents: %d functions scanned, %d events with users -> %s", work.size(), list.size(), out));
    }

    private void annotate(Map<String, Map<String, Set<String>>> events) {
        Map<String, Map<String, Set<String>>> byFunction = new HashMap<>();
        for (Map.Entry<String, Map<String, Set<String>>> e : events.entrySet()) {
            for (Map.Entry<String, Set<String>> role : e.getValue().entrySet()) {
                for (String fn : role.getValue()) {
                    byFunction.computeIfAbsent(fn, k -> new TreeMap<>()).computeIfAbsent(role.getKey(), k -> new TreeSet<>())
                            .add(e.getKey());
                }
            }
        }
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            Map<String, Set<String>> roles = byFunction.get(f.getName(true));
            String text = null;
            if (roles != null) {
                StringBuilder sb = new StringBuilder("Events:");
                for (Map.Entry<String, Set<String>> r : roles.entrySet()) {
                    sb.append("\n  ").append(r.getKey()).append(": ").append(String.join(", ", r.getValue()));
                }
                text = sb.toString();
            }
            String current = f.getRepeatableComment();
            if (text != null || (current != null && current.startsWith("Events:"))) {
                f.setRepeatableComment(text);
            }
        }
    }

    private void add(Map<String, Map<String, Set<String>>> events, String ev, String role, Function f) {
        events.computeIfAbsent(ev, k -> new TreeMap<>()).computeIfAbsent(role, k -> new TreeSet<>()).add(f.getName(true));
    }

    private List<Function> functionsNamed(String qualified) {
        List<Function> out = new ArrayList<>();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (f.getName(true).equals(qualified)) {
                out.add(f);
            }
        }
        return out;
    }

    // The event an id argument comes from: a load of a hash_SUBJECT_* global (directly or through
    // its pointer slot).
    private String eventOf(Varnode v) {
        for (int i = 0; v != null && i < 6; i++) {
            PcodeOp def = v.getDef();
            if (def == null) {
                return null;
            }
            if (def.getOpcode() == PcodeOp.LOAD) {
                return eventAt(def.getInput(1));
            }
            if (def.getOpcode() != PcodeOp.COPY && def.getOpcode() != PcodeOp.CAST
                    && def.getOpcode() != PcodeOp.INDIRECT && def.getOpcode() != PcodeOp.MULTIEQUAL) {
                return null;
            }
            v = def.getInput(0);
        }
        return null;
    }

    private String eventAt(Varnode pointer) {
        Long a = constant(pointer, 6);
        if (a == null) {
            // a load through a loaded pointer slot: *(*slot)
            PcodeOp def = pointer == null ? null : pointer.getDef();
            if (def != null && def.getOpcode() == PcodeOp.LOAD) {
                Long slot = constant(def.getInput(1), 6);
                if (slot != null) {
                    try {
                        return subjectLabel(toAddr(getInt(toAddr(slot)) & 0xffffffffL));
                    } catch (Exception e) {
                        return null;
                    }
                }
            }
            return null;
        }
        String name = subjectLabel(toAddr(a));
        if (name != null) {
            return name;
        }
        try {
            return subjectLabel(toAddr(getInt(toAddr(a)) & 0xffffffffL));
        } catch (Exception e) {
            return null;
        }
    }

    private String subjectLabel(Address a) {
        for (Symbol s : currentProgram.getSymbolTable().getSymbols(a)) {
            if (s.getName().startsWith("hash_SUBJECT_")) {
                return s.getName().substring("hash_".length());
            }
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
