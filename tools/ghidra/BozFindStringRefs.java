// Finds the functions that use given string (or any data) addresses. The game reaches data
// PIC-style (a literal-pool word plus pc, e.g. `ldr r1,[pc,#x]; add r1,pc`), which Ghidra's own
// references miss; this resolves both absolute pool words and pool word + pc.
// Args: hex addresses. Prints "address [function@entry, ...]".
// @category BOZ
// @menupath Tools.BOZ.Find String References

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.symbol.Reference;

import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;

public class BozFindStringRefs extends GhidraScript {
    @Override
    protected void run() throws Exception {
        Set<Long> targets = new HashSet<>();
        for (String s : getScriptArgs()) {
            targets.add(Long.parseLong(s.replace("0x", ""), 16));
        }
        Map<Long, Set<String>> hits = new TreeMap<>();
        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            if (!ins.getMnemonicString().startsWith("ldr")) {
                continue;
            }
            for (Reference r : ins.getReferencesFrom()) {
                long word;
                try {
                    word = currentProgram.getMemory().getInt(r.getToAddress()) & 0xffffffffL;
                } catch (Exception e) {
                    continue;
                }
                if (targets.contains(word)) {
                    add(hits, word, ins);
                }
                // The matching `add rX, pc` follows within a few instructions (Thumb pc = +4, ARM = +8).
                Instruction n = ins;
                for (int k = 0; k < 6 && n != null; k++, n = n.getNext()) {
                    if (n.getMnemonicString().startsWith("add") && n.toString().contains("pc")) {
                        for (long bias : new long[] {4, 8}) {
                            long v = (word + n.getAddress().getOffset() + bias) & 0xffffffffL;
                            if (targets.contains(v)) {
                                add(hits, v, ins);
                            }
                        }
                        break;
                    }
                }
            }
        }
        for (Map.Entry<Long, Set<String>> e : hits.entrySet()) {
            println(Long.toHexString(e.getKey()) + " " + e.getValue());
        }
    }

    private void add(Map<Long, Set<String>> hits, long target, Instruction ins) {
        Function f = getFunctionContaining(ins.getAddress());
        hits.computeIfAbsent(target, x -> new TreeSet<>())
                .add(f == null ? ins.getAddress().toString() : f.getName(true) + "@" + f.getEntryPoint());
    }
}
