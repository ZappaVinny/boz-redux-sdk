// Creates the Thumb functions that BOZ only reaches through stored pointers (callbacks, C++
// virtual methods), which Ghidra's analysis does not find on its own. Reads the list written by
// tools/ghidra/s3e_to_elf.py next to the imported ELF (<elf>.code-pointers.txt).
// Safe to run again: existing functions are left alone.
// @category BOZ
// @menupath Tools.BOZ.Seed Functions From Code Pointers

import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;

import java.io.File;
import java.nio.file.Files;
import java.util.List;

public class BozSeedFunctions extends GhidraScript {
    @Override
    protected void run() throws Exception {
        File list;
        String[] args = getScriptArgs();
        if (args.length > 0) {
            list = new File(args[0]);
        } else {
            list = new File(currentProgram.getExecutablePath() + ".code-pointers.txt");
            if (!list.exists()) {
                list = askFile("Code pointer list (from s3e_to_elf.py)", "Use");
            }
        }
        List<String> lines = Files.readAllLines(list.toPath());
        int created = 0;
        int existing = 0;
        int failed = 0;
        monitor.initialize(lines.size());
        monitor.setMessage("Seeding Thumb functions");
        for (String line : lines) {
            monitor.checkCancelled();
            monitor.incrementProgress(1);
            line = line.trim();
            if (line.isEmpty()) {
                continue;
            }
            Address address = toAddr(Long.parseLong(line, 16));
            Function function = getFunctionAt(address);
            if (function != null) {
                existing++;
                continue;
            }
            Instruction instruction = getInstructionAt(address);
            if (instruction == null) {
                if (getDataAt(address) != null && getDataAt(address).isDefined()) {
                    failed++;  // analysis typed it as data; leave it for a human to look at
                    continue;
                }
                ArmDisassembleCommand disassemble = new ArmDisassembleCommand(address, null, true);
                if (!disassemble.applyTo(currentProgram, monitor) || getInstructionAt(address) == null) {
                    failed++;
                    continue;
                }
            }
            CreateFunctionCmd create = new CreateFunctionCmd(address);
            if (create.applyTo(currentProgram, monitor)) {
                created++;
            } else {
                failed++;
            }
        }
        println(String.format("BozSeedFunctions: %d created, %d already functions, %d skipped",
                created, existing, failed));
    }
}
