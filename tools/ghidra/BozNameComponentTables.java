// Maps the studio entity/component system: every component type T has one global
// CIsComponentTable<T>, constructed at startup, that stores T components keyed by entity id.
// This script finds which global each CIsComponentTable<T> constructor builds, labels it
// T::s_table, and names the small getters that look an entity's component up in it
// (T::FromEntity). Run ApplyBozClasses first (it names the table constructors).
// Names are created with source ANALYSIS (rebuildable, not exported).
// @category BOZ
// @menupath Tools.BOZ.Name Component Tables

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.pcode.HighFunction;
import ghidra.program.model.pcode.PcodeOp;
import ghidra.program.model.pcode.PcodeOpAST;
import ghidra.program.model.pcode.Varnode;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;

import java.util.HashMap;
import java.util.Iterator;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

public class BozNameComponentTables extends GhidraScript {
    private static final String PREFIX = "CIsComponentTable<";

    @Override
    protected void run() throws Exception {
        // Table constructors by component type.
        Map<Address, String> constructors = new HashMap<>();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            Namespace ns = f.getParentNamespace();
            if (ns.getName().startsWith(PREFIX) && f.getName().equals(ns.getName())) {
                constructors.put(f.getEntryPoint(), ns.getName().substring(PREFIX.length(), ns.getName().length() - 1));
            }
        }
        Set<Function> callers = new LinkedHashSet<>();
        for (Address ctor : constructors.keySet()) {
            for (Reference r : getReferencesTo(ctor)) {
                Function f = getFunctionContaining(r.getFromAddress());
                if (r.getReferenceType().isCall() && f != null) {
                    callers.add(f);
                }
            }
        }

        // The global each constructor call builds (its first argument).
        Map<Address, String> tables = new HashMap<>();
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        for (Function caller : callers) {
            monitor.checkCancelled();
            HighFunction high = decompiler.decompileFunction(caller, 30, monitor).getHighFunction();
            if (high == null) {
                continue;
            }
            for (Iterator<PcodeOpAST> it = high.getPcodeOps(); it.hasNext();) {
                PcodeOpAST op = it.next();
                if (op.getOpcode() != PcodeOp.CALL || op.getNumInputs() < 2) {
                    continue;
                }
                String type = constructors.get(op.getInput(0).getAddress());
                Long table = type == null ? null : constant(op.getInput(1), 6);
                if (table != null) {
                    tables.put(toAddr(table), type);
                }
            }
        }

        int labelled = 0;
        int getters = 0;
        for (Map.Entry<Address, String> table : tables.entrySet()) {
            Namespace ns = classNamespace(table.getValue());
            if (ns == null) {
                continue;
            }
            if (!hasLabel(table.getKey(), "s_table", ns)) {
                currentProgram.getSymbolTable().createLabel(table.getKey(), "s_table", ns, SourceType.ANALYSIS);
                labelled++;
            }
            // Getters: small functions referencing the table (look-ups by entity id).
            for (Reference r : getReferencesTo(table.getKey())) {
                Function f = getFunctionContaining(r.getFromAddress());
                if (f == null || f.getBody().getNumAddresses() > 40 || f.getSymbol().getSource() != SourceType.DEFAULT) {
                    continue;
                }
                try {
                    f.getSymbol().setNameAndNamespace("FromEntity", ns, SourceType.ANALYSIS);
                    getters++;
                } catch (Exception e) {
                    // a second getter for the same type: keep its default name
                }
            }
        }
        decompiler.dispose();
        println(String.format("BozNameComponentTables: %d table constructors, %d tables found, %d labelled, %d getters named",
                constructors.size(), tables.size(), labelled, getters));
    }

    private boolean hasLabel(Address address, String name, Namespace ns) {
        for (Symbol s : currentProgram.getSymbolTable().getSymbols(address)) {
            if (s.getName().equals(name) && s.getParentNamespace().equals(ns)) {
                return true;
            }
        }
        return false;
    }

    private Namespace classNamespace(String name) {
        // Only top-level classes; nested component types are rare.
        Namespace ns = getNamespace(null, ghidra.program.model.symbol.SymbolUtilities.replaceInvalidChars(name.replace(", ", ","), true));
        return ns;
    }

    private Long constant(Varnode v, int depth) {
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
