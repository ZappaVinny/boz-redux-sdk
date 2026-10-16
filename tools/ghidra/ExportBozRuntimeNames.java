// Lists the names each function of the game uses at run time: the strings it reaches (literal
// pool word, or word + pc, the way the game addresses data) and the hash_<name> globals it reads
// (named by BozNameHashGlobals: IwHashString("<name>") cached once). bozkit turns this into the
// gamedef's runtime names: what a class plays or spawns by name (the Gersch device's
// gersch_Effect and sounds), so a map that uses the class carries those resources too.
// Output: JSON {"functions": [{"name", "namespace", "entry", "strings": [...], "hashes": [...]}]}
// (functions that use at least one) to the given path.
// @category BOZ
// @menupath Tools.BOZ.Export Runtime Names

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.Symbol;

import java.io.File;
import java.io.FileWriter;
import java.util.Set;
import java.util.TreeSet;

public class ExportBozRuntimeNames extends GhidraScript {
    private Memory memory;

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File out = args.length > 0 ? new File(args[0]) : askFile("Write runtime names JSON", "Export");
        memory = currentProgram.getMemory();
        JsonArray functions = new JsonArray();
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        int total = currentProgram.getFunctionManager().getFunctionCount();
        monitor.initialize(total);
        monitor.setMessage("Runtime names");
        while (it.hasNext()) {
            monitor.checkCancelled();
            monitor.incrementProgress(1);
            Function f = it.next();
            Set<String> strings = new TreeSet<>();
            Set<String> hashes = new TreeSet<>();
            InstructionIterator ins = currentProgram.getListing().getInstructions(f.getBody(), true);
            while (ins.hasNext()) {
                Instruction i = ins.next();
                for (Reference r : i.getReferencesFrom()) {
                    note(r.getToAddress(), strings, hashes);
                    if (!i.getMnemonicString().startsWith("ldr")) {
                        continue;
                    }
                    long word;
                    try {
                        word = memory.getInt(r.getToAddress()) & 0xffffffffL;
                    } catch (Exception e) {
                        continue;
                    }
                    note(toAddr(word), strings, hashes);
                    Instruction n = i;
                    for (int k = 0; k < 6 && n != null; k++, n = n.getNext()) {
                        if (n.getMnemonicString().startsWith("add") && n.toString().contains("pc")) {
                            for (long bias : new long[] {4, 8}) {
                                note(toAddr((word + n.getAddress().getOffset() + bias) & 0xffffffffL),
                                     strings, hashes);
                            }
                            break;
                        }
                    }
                }
            }
            if (strings.isEmpty() && hashes.isEmpty()) {
                continue;
            }
            JsonObject entry = new JsonObject();
            entry.addProperty("name", f.getName(true));
            entry.addProperty("namespace", f.getParentNamespace().isGlobal() ? "" : f.getParentNamespace().getName(true));
            entry.addProperty("entry", "0x" + Long.toHexString(f.getEntryPoint().getOffset()));
            JsonArray s = new JsonArray();
            strings.forEach(s::add);
            JsonArray h = new JsonArray();
            hashes.forEach(h::add);
            entry.add("strings", s);
            entry.add("hashes", h);
            functions.add(entry);
        }
        JsonObject root = new JsonObject();
        root.add("functions", functions);
        try (FileWriter w = new FileWriter(out)) {
            new GsonBuilder().setPrettyPrinting().create().toJson(root, w);
        }
        println("ExportBozRuntimeNames: " + functions.size() + " functions -> " + out);
    }

    private void note(Address a, Set<String> strings, Set<String> hashes) {
        if (a == null || !memory.contains(a)) {
            return;
        }
        Data d = getDataAt(a);
        if (d != null && d.hasStringValue()) {
            Object v = d.getValue();
            if (v != null) {
                String text = v.toString();
                if (text.length() >= 3 && text.length() <= 64 && text.matches("[A-Za-z0-9_./ -]+")) {
                    strings.add(text);
                }
            }
            return;
        }
        Symbol s = getSymbolAt(a);
        if (s != null && s.getName().startsWith("hash_")) {
            hashes.add(s.getName().substring(5));
            return;
        }
        // A GOT-style pointer to the hash global.
        try {
            long target = memory.getInt(a) & 0xffffffffL;
            Address t = toAddr(target);
            if (memory.contains(t)) {
                Symbol g = getSymbolAt(t);
                if (g != null && g.getName().startsWith("hash_")) {
                    hashes.add(g.getName().substring(5));
                }
            }
        } catch (Exception e) {
            // not readable
        }
    }
}
