// Repairs virtual functions (from rtti_classes.py's class map) that Ghidra never disassembled
// because they sit inside the body of a neighbouring function, usually small Thumb functions
// right after another function's end. Disassembles each in its vtable's mode, then re-creates
// the swallowing function and the new one so both get correct bodies. Names, namespaces and tags
// of re-created functions are preserved. Run ApplyBozClasses again afterwards to name them.
// @category BOZ
// @menupath Tools.BOZ.Repair Virtual Functions

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionTag;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;

import java.io.File;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.List;

public class BozRepairVirtuals extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File file = args.length > 0 ? new File(args[0]) : askFile("Class map JSON (rtti_classes.py)", "Repair");
        JsonObject map;
        try (FileReader reader = new FileReader(file)) {
            map = JsonParser.parseReader(reader).getAsJsonObject();
        }
        Address base = currentProgram.getImageBase();
        int repaired = 0;
        int failed = 0;
        for (JsonElement element : map.getAsJsonArray("virtual_functions")) {
            monitor.checkCancelled();
            JsonObject entry = element.getAsJsonObject();
            Address address = base.add(entry.get("address").getAsLong());
            if (getInstructionAt(address) != null) {
                continue;
            }
            boolean thumb = entry.get("thumb").getAsBoolean();
            Function outer = getFunctionContaining(address);
            // Bytes here are defined as data (or strings): clear them up to the next instruction
            // so the disassembler can start (it only starts on undefined code units).
            Address end = address;
            for (int i = 0; i < 256 && getInstructionAt(end.add(1)) == null; i++) {
                end = end.add(1);
            }
            if (getDataContaining(address) != null) {
                Address start = getDataContaining(address).getMinAddress();
                if (start.compareTo(address) < 0) {
                    end = end.compareTo(getDataContaining(address).getMaxAddress()) > 0 ? end
                            : getDataContaining(address).getMaxAddress();
                    address = address;  // the data starts earlier; clear it whole
                    clearListing(start, end);
                } else {
                    clearListing(address, end);
                }
            } else {
                clearListing(address, end);
            }
            if (outer != null && outer.getEntryPoint().equals(address) && outer.getBody().getNumAddresses() <= 1) {
                outer = null;  // a degenerate function created on the data; re-created below
                Function degenerate = getFunctionAt(address);
                Saved saved = new Saved(degenerate);
                removeFunction(degenerate);
                new ArmDisassembleCommand(address, null, thumb).applyTo(currentProgram, monitor);
                new CreateFunctionCmd(address).applyTo(currentProgram, monitor);
                saved.restore(getFunctionAt(address));
                if (getFunctionAt(address) != null && getInstructionAt(address) != null) {
                    repaired++;
                } else {
                    failed++;
                }
                continue;
            }
            new ArmDisassembleCommand(address, null, thumb).applyTo(currentProgram, monitor);
            if (getInstructionAt(address) == null) {
                failed++;
                continue;
            }
            if (outer != null && !outer.getEntryPoint().equals(address)) {
                Saved saved = new Saved(outer);
                removeFunction(outer);
                new CreateFunctionCmd(saved.entry).applyTo(currentProgram, monitor);
                saved.restore(getFunctionAt(saved.entry));
            }
            new CreateFunctionCmd(address).applyTo(currentProgram, monitor);
            if (getFunctionAt(address) != null) {
                repaired++;
            } else {
                failed++;
            }
        }
        println(String.format("BozRepairVirtuals: %d virtual functions repaired, %d failed", repaired, failed));
    }

    // Name, namespace, source, tags and comment of a function being re-created.
    private class Saved {
        final Address entry;
        final String name;
        final Namespace namespace;
        final SourceType source;
        final String comment;
        final List<String> tags = new ArrayList<>();

        Saved(Function f) {
            entry = f.getEntryPoint();
            name = f.getName();
            namespace = f.getParentNamespace();
            source = f.getSymbol().getSource();
            comment = f.getComment();
            for (FunctionTag tag : f.getTags()) {
                tags.add(tag.getName());
            }
        }

        void restore(Function f) throws Exception {
            if (f == null) {
                return;
            }
            if (source != SourceType.DEFAULT) {
                f.getSymbol().setNameAndNamespace(name, namespace, source);
            }
            f.setComment(comment);
            for (String tag : tags) {
                f.addTag(tag);
            }
        }
    }
}
