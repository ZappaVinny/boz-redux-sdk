// Lists the game's console variables (cvars): every call to the CIwConsole registration
// wrappers, with the cvar's name, type, default value, the global that holds the registered
// cvar (its value is at +0x10), and where it is registered.
//
// The wrappers are found by shape: small functions that call CIwConsole's register method with
// a "cvar<type>" tag. Output: JSON (array of cvars) to the given path.
// @category BOZ
// @menupath Tools.BOZ.Export Console Variables

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.pcode.HighFunction;
import ghidra.program.model.pcode.PcodeOp;
import ghidra.program.model.pcode.PcodeOpAST;
import ghidra.program.model.pcode.Varnode;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.io.FileWriter;
import java.util.HashMap;
import java.util.Iterator;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

public class ExportBozCvars extends GhidraScript {
    private final Map<Address, String> wrappers = new HashMap<>();

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File out = args.length > 0 ? new File(args[0]) : askFile("Write cvar list JSON", "Export");
        findWrappers();
        println("ExportBozCvars: " + wrappers.size() + " registration wrappers " + wrappers.values());

        Set<Function> callers = new LinkedHashSet<>();
        for (Address wrapper : wrappers.keySet()) {
            for (Reference ref : getReferencesTo(wrapper)) {
                if (ref.getReferenceType().isCall()) {
                    Function f = getFunctionContaining(ref.getFromAddress());
                    if (f != null) {
                        callers.add(f);
                    }
                }
            }
        }

        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        JsonArray cvars = new JsonArray();
        int failed = 0;
        monitor.initialize(callers.size());
        monitor.setMessage("Decompiling cvar registrations");
        for (Function caller : callers) {
            monitor.checkCancelled();
            monitor.incrementProgress(1);
            DecompileResults result = decompiler.decompileFunction(caller, 60, monitor);
            HighFunction high = result.getHighFunction();
            if (high == null) {
                failed++;
                continue;
            }
            Iterator<PcodeOpAST> ops = high.getPcodeOps();
            while (ops.hasNext()) {
                PcodeOpAST op = ops.next();
                if (op.getOpcode() != PcodeOp.CALL) {
                    continue;
                }
                Address target = op.getInput(0).getAddress();
                String type = wrappers.get(target);
                if (type == null) {
                    continue;
                }
                JsonObject cvar = new JsonObject();
                cvar.addProperty("name", string(op.getNumInputs() > 1 ? op.getInput(1) : null));
                cvar.addProperty("type", type);
                cvar.addProperty("default", string(op.getNumInputs() > 2 ? op.getInput(2) : null));
                Address global = storedTo(op.getOutput());
                if (global != null) {
                    cvar.addProperty("global", global.subtract(currentProgram.getImageBase()));
                }
                cvar.addProperty("registered_in", caller.getName(true));
                cvar.addProperty("call", op.getSeqnum().getTarget().subtract(currentProgram.getImageBase()));
                cvars.add(cvar);
            }
        }
        decompiler.dispose();
        try (FileWriter writer = new FileWriter(out)) {
            new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create().toJson(cvars, writer);
        }
        println(String.format("ExportBozCvars: %d cvars from %d functions (%d not decompiled) -> %s",
                cvars.size(), callers.size(), failed, out));
    }

    // Wrappers: functions referencing a pointer to a "cvar..." string and calling through a vtable.
    private void findWrappers() throws Exception {
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            if (f.getBody().getNumAddresses() > 80) {
                continue;
            }
            for (Instruction ins : currentProgram.getListing().getInstructions(f.getBody(), true)) {
                for (Reference ref : ins.getReferencesFrom()) {
                    String tag = cvarTag(ref.getToAddress(), 3);
                    if (tag != null) {
                        wrappers.put(f.getEntryPoint(), tag);
                    }
                }
            }
        }
    }

    // Follows up to `hops` pointers looking for a "cvar..." string.
    private String cvarTag(Address address, int hops) throws Exception {
        String text = readString(address);
        if (text != null && text.startsWith("cvar") && text.length() < 20) {
            return text;
        }
        if (hops == 0) {
            return null;
        }
        Data data = getDataAt(address);
        if (data != null && data.isPointer() && data.getValue() instanceof Address) {
            return cvarTag((Address) data.getValue(), hops - 1);
        }
        try {
            long value = currentProgram.getMemory().getInt(address) & 0xffffffffL;
            Address next = toAddr(value);
            if (currentProgram.getMemory().contains(next)) {
                return cvarTag(next, hops - 1);
            }
        } catch (Exception e) {
            // not readable as a pointer
        }
        return null;
    }

    private String readString(Address address) {
        try {
            StringBuilder text = new StringBuilder();
            for (int i = 0; i < 160; i++) {
                byte b = currentProgram.getMemory().getByte(address.add(i));
                if (b == 0) {
                    return text.length() > 0 ? text.toString() : null;
                }
                if (b < 0x20 || b > 0x7e) {
                    return null;
                }
                text.append((char) b);
            }
        } catch (Exception e) {
            // out of memory range
        }
        return null;
    }

    // A constant pointer argument (possibly through COPY/CAST/PTRSUB/INT_ADD) to a string.
    private String string(Varnode v) {
        Long address = constantAddress(v, 6);
        if (address == null) {
            return null;
        }
        return readString(toAddr(address));
    }

    private Long constantAddress(Varnode v, int depth) {
        if (v == null || depth == 0) {
            return null;
        }
        if (v.isConstant()) {
            return v.getOffset();
        }
        if (v.isAddress()) {
            // A literal-pool word in the code: position-independent code loads it and adds the PC.
            Address word = v.getAddress();
            ghidra.program.model.mem.MemoryBlock block = currentProgram.getMemory().getBlock(word);
            if (block != null && block.isExecute()) {
                try {
                    return currentProgram.getMemory().getInt(word) & 0xffffffffL;
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
                return constantAddress(def.getInput(0), depth - 1);
            case PcodeOp.PTRSUB:
            case PcodeOp.INT_ADD: {
                Long a = constantAddress(def.getInput(0), depth - 1);
                Long b = constantAddress(def.getInput(1), depth - 1);
                return a != null && b != null ? (a + b) & 0xffffffffL : null;
            }
            default:
                return null;
        }
    }

    // Where the registered cvar pointer is stored: a global written with the call's result.
    private Address storedTo(Varnode output) {
        if (output == null) {
            return null;
        }
        if (output.isAddress()) {
            return output.getAddress();
        }
        Iterator<PcodeOp> uses = output.getDescendants();
        while (uses.hasNext()) {
            PcodeOp use = uses.next();
            if (use.getOpcode() == PcodeOp.STORE) {
                Long address = constantAddress(use.getInput(1), 6);
                if (address != null) {
                    return toAddr(address);
                }
            }
            if (use.getOpcode() == PcodeOp.COPY && use.getOutput() != null && use.getOutput().isAddress()) {
                return use.getOutput().getAddress();
            }
        }
        return null;
    }
}
