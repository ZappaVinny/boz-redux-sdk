// The game's position-independent code reaches most globals through a table of pointers in .data
// (a GOT): code loads the slot, then the global. Untyped, the decompiler prints `*DAT_4a412eec`.
// This types each such slot as a pointer when it points at a named global, so the decompiler
// shows the global's name instead (`*PTR_hash_EVENT_ROUND_START_4a412eec`). A slot qualifies when
// code reads it, it holds an address inside the image, and the target has a non-default name.
// Run after the naming scripts (singletons, hash globals, symbol database).
// @category BOZ
// @menupath Tools.BOZ.Type GOT Pointers

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.PointerDataType;
import ghidra.program.model.listing.Data;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;

public class BozTypeGotPointers extends GhidraScript {
    @Override
    protected void run() throws Exception {
        MemoryBlock data = currentProgram.getMemory().getBlock(".data");
        MemoryBlock text = currentProgram.getMemory().getBlock(".text");
        long lo = text.getStart().getOffset();
        long hi = data.getEnd().getOffset();
        int typed = 0;
        int skipped = 0;
        for (Address a = data.getStart(); a.compareTo(data.getEnd()) < 0; a = a.add(4)) {
            monitor.checkCancelled();
            long value = getInt(a) & 0xffffffffL;
            if (value < lo || value > hi) {
                continue;
            }
            Symbol target = getSymbolAt(toAddr(value));
            if (target == null || target.getSource() == SourceType.DEFAULT) {
                continue;
            }
            if (!readByCode(a)) {
                continue;
            }
            Data existing = getDataAt(a);
            if (existing != null && existing.isPointer()) {
                continue;
            }
            try {
                clearListing(a, a.add(3));
                createData(a, PointerDataType.dataType);
                typed++;
            } catch (Exception e) {
                skipped++;
            }
        }
        println(String.format("BozTypeGotPointers: %d pointer slots typed, %d skipped", typed, skipped));
    }

    private boolean readByCode(Address a) {
        ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(a);
        while (refs.hasNext()) {
            Reference r = refs.next();
            if (getInstructionAt(r.getFromAddress()) != null) {
                return true;
            }
        }
        return false;
    }
}
