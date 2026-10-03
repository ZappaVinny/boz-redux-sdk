// Finds the instance global of every studio singleton (CIsSingleton<T>): the constructor of T, or of
// CIsSingleton<T>, stores `this` into one fixed global, and the destructor clears it. Labels the
// global T::s_instance (falling back to the global the destructor clears; source ANALYSIS: rebuilt, not exported) and prints each with its use count.
// Run ApplyBozClasses first (it names constructors and destructors).
// @category BOZ
// @menupath Tools.BOZ.Name Singletons

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.pcode.HighFunction;
import ghidra.program.model.pcode.HighVariable;
import ghidra.program.model.pcode.PcodeOp;
import ghidra.program.model.pcode.PcodeOpAST;
import ghidra.program.model.pcode.Varnode;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;

import java.util.*;

public class BozNameSingletons extends GhidraScript {
    private static final String PREFIX = "CIsSingleton<";

    @Override
    protected void run() throws Exception {
        // T for every CIsSingleton<T> class.
        Set<String> types = new TreeSet<>();
        for (Namespace ns : listNamespaces()) {
            String n = ns.getName();
            if (n.startsWith(PREFIX) && n.endsWith(">")) {
                types.add(n.substring(PREFIX.length(), n.length() - 1));
            }
        }
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        int labelled = 0;
        List<String> missing = new ArrayList<>();
        for (String type : types) {
            monitor.checkCancelled();
            Namespace ns = getNamespace(null, type);
            Namespace single = getNamespace(null, PREFIX + type + ">");
            Address instance = null;
            for (Namespace n : new Namespace[] {ns, single}) {
                if (n == null || instance != null) {
                    continue;
                }
                for (Function f : functionsIn(n)) {
                    String name = f.getName();
                    boolean ctor = name.equals(n.getName());
                    if (!ctor) {
                        continue;
                    }
                    instance = storedThis(decompiler, f);
                    if (instance != null) {
                        break;
                    }
                }
            }
            // Fallback: the destructor clears the instance (stores 0 into the global).
            for (Namespace n : new Namespace[] {ns, single}) {
                if (n == null || instance != null) {
                    continue;
                }
                for (Function f : functionsIn(n)) {
                    if (f.getName().startsWith("~")) {
                        instance = clearedGlobal(decompiler, f);
                        if (instance != null) {
                            break;
                        }
                    }
                }
            }
            if (instance == null) {
                missing.add(type);
                continue;
            }
            if (ns == null) {
                ns = currentProgram.getSymbolTable().createClass(currentProgram.getGlobalNamespace(), type, SourceType.ANALYSIS);
            }
            boolean has = false;
            for (Symbol s : currentProgram.getSymbolTable().getSymbols(instance)) {
                has |= s.getName().equals("s_instance");
            }
            if (!has) {
                currentProgram.getSymbolTable().createLabel(instance, "s_instance", ns, SourceType.ANALYSIS);
                labelled++;
            }
            println(String.format("%-40s %s  refs=%d", type, instance, getReferencesTo(instance).length));
        }
        decompiler.dispose();
        println(String.format("BozNameSingletons: %d singleton types, %d labelled, %d without an instance store: %s",
                types.size(), labelled, missing.size(), missing));
    }

    private List<Namespace> listNamespaces() {
        List<Namespace> out = new ArrayList<>();
        Iterator<ghidra.program.model.listing.GhidraClass> it = currentProgram.getSymbolTable().getClassNamespaces();
        while (it.hasNext()) {
            out.add(it.next());
        }
        return out;
    }

    private List<Function> functionsIn(Namespace ns) {
        List<Function> out = new ArrayList<>();
        for (Symbol s : currentProgram.getSymbolTable().getSymbols(ns)) {
            if (s.getSymbolType() == ghidra.program.model.symbol.SymbolType.FUNCTION) {
                out.add((Function) s.getObject());
            }
        }
        return out;
    }

    // The global that `this` (param 0) is stored into, if any.
    private Address storedThis(DecompInterface decompiler, Function f) {
        DecompileResults r = decompiler.decompileFunction(f, 30, monitor);
        HighFunction high = r == null ? null : r.getHighFunction();
        if (high == null || high.getFunctionPrototype().getNumParams() == 0) {
            return null;
        }
        HighVariable self = high.getFunctionPrototype().getParam(0).getHighVariable();
        for (Iterator<PcodeOpAST> it = high.getPcodeOps(); it.hasNext();) {
            PcodeOpAST op = it.next();
            if (op.getOpcode() != PcodeOp.STORE || op.getInput(2).getHigh() != self) {
                continue;
            }
            Long a = constant(op.getInput(1), 6);
            if (a != null) {
                MemoryBlock block = currentProgram.getMemory().getBlock(toAddr(a));
                if (block != null && !block.isExecute()) {
                    return toAddr(a);
                }
            }
        }
        return null;
    }

    // The single data global a destructor stores constant 0 into (its first such store).
    private Address clearedGlobal(DecompInterface decompiler, Function f) {
        DecompileResults r = decompiler.decompileFunction(f, 30, monitor);
        HighFunction high = r == null ? null : r.getHighFunction();
        if (high == null) {
            return null;
        }
        for (Iterator<PcodeOpAST> it = high.getPcodeOps(); it.hasNext();) {
            PcodeOpAST op = it.next();
            if (op.getOpcode() != PcodeOp.STORE || !op.getInput(2).isConstant() || op.getInput(2).getOffset() != 0) {
                continue;
            }
            Long a = constant(op.getInput(1), 6);
            if (a != null) {
                MemoryBlock block = currentProgram.getMemory().getBlock(toAddr(a));
                if (block != null && !block.isExecute()) {
                    return toAddr(a);
                }
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
