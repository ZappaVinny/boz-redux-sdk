// Lists the game's developer console commands. Systems register them with the console
// (g_console vtable +0x58: RegisterCommand(name, id, handler, flags), directly or through
// Console_RegisterCommand(handler, name, id, flags)); the handler's
// IIwConsoleHandler slot later receives (id, args). Reads the decompiled callers of g_console and
// writes name, id, the registering function and its class to JSON.
// Args: output JSON path.
// @category BOZ
// @menupath Tools.BOZ.Export Console Commands

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.Symbol;

import java.io.File;
import java.io.FileWriter;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class ExportBozCommands extends GhidraScript {
    private static final Pattern WRAPPED =
            Pattern.compile("Console_RegisterCommand\\(\\s*[^,]+,\\s*\"([^\"]+)\"\\s*,\\s*(0x[0-9a-f]+|\\d+)");
    private static final Pattern REGISTER =
            Pattern.compile("\\(\\*\\*\\(code \\*\\*\\)\\(\\*g_console \\+ 0x58\\)\\)\\s*\\(\\s*g_console\\s*,\\s*\"([^\"]+)\"\\s*,\\s*(0x[0-9a-f]+|\\d+)");

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File out = args.length > 0 ? new File(args[0]) : askFile("Write console commands JSON", "Export");
        Symbol console = getSymbols("g_console", null).isEmpty() ? null : getSymbols("g_console", null).get(0);
        if (console == null) {
            printerr("g_console not found; apply the symbol database first");
            return;
        }
        Set<Function> users = new LinkedHashSet<>();
        collect(console.getAddress(), users);
        // Code reaches g_console through pointer slots too.
        for (Reference r : getReferencesTo(console.getAddress())) {
            if (getInstructionAt(r.getFromAddress()) == null) {
                collect(r.getFromAddress(), users);
            }
        }
        for (Function wrapper : getGlobalFunctions("Console_RegisterCommand")) {
            collect(wrapper.getEntryPoint(), users);
        }
        DecompInterface decompiler = new DecompInterface();
        // The program's decompiler options fold the PIC address arithmetic into string literals,
        // which the pattern below needs.
        ghidra.app.decompiler.DecompileOptions options = new ghidra.app.decompiler.DecompileOptions();
        options.grabFromProgram(currentProgram);
        decompiler.setOptions(options);
        decompiler.openProgram(currentProgram);
        Map<String, JsonObject> commands = new TreeMap<>();
        for (Function f : users) {
            monitor.checkCancelled();
            DecompileResults r = decompiler.decompileFunction(f, 30, monitor);
            if (r == null || r.getDecompiledFunction() == null) {
                continue;
            }
            String code = r.getDecompiledFunction().getC();
            for (Pattern p : new Pattern[] {REGISTER, WRAPPED}) {
            Matcher m = p.matcher(code);
            while (m.find()) {
                JsonObject c = new JsonObject();
                c.addProperty("name", m.group(1));
                c.addProperty("id", Long.decode(m.group(2)));
                c.addProperty("registered_in", f.getName(true));
                String ns = f.getParentNamespace().isGlobal() ? null : f.getParentNamespace().getName(true);
                if (ns != null) {
                    c.addProperty("class", ns);
                }
                commands.putIfAbsent(m.group(1) + "/" + f.getName(true), c);
            }
            }
        }
        decompiler.dispose();
        JsonArray list = new JsonArray();
        commands.values().forEach(list::add);
        JsonObject report = new JsonObject();
        report.add("commands", list);
        try (FileWriter w = new FileWriter(out)) {
            new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create().toJson(report, w);
        }
        println(String.format("ExportBozCommands: %d functions read, %d commands -> %s", users.size(), list.size(), out));
    }

    private void collect(Address target, Set<Function> users) {
        for (Reference r : getReferencesTo(target)) {
            Function f = getFunctionContaining(r.getFromAddress());
            if (f != null) {
                users.add(f);
            }
        }
    }
}
