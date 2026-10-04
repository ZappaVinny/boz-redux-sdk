// Finds console variables that ExportBozCvars misses: ones registered by calling the console's
// register method directly (g_console vtable +0x5c, no Cvar_Register* wrapper), and names the
// code only reads through Cvar_GetIntOr (0x0e5ecc) without registering them. Decompiles every
// function that uses g_console or Cvar_GetIntOr and matches the call shapes in the C output.
// Output: JSON array of {name, default, kind: registered|lookup, registered_in} for
// `tools/symbols/symbols.py console ... --direct re/cvars-direct.json`.
// @category BOZ
// @menupath Tools.BOZ.Export Direct Console Variables

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.nio.file.Files;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class ExportBozDirectCvars extends GhidraScript {
    private static final long G_CONSOLE = 0x4a4506f8L;
    private static final long CVAR_GET_INT_OR = 0x4a0e5eccL;
    private static final Pattern REGISTER =
        Pattern.compile("\\(\\*pcVar\\d+\\)\\([^,]+,\"([A-Za-z0-9_]+)\",\"([^\"]*)\"");
    private static final Pattern LOOKUP = Pattern.compile("FUN_4a0e5ecc\\(\"([A-Za-z0-9_]+)\"");

    private final Set<String> seen = new LinkedHashSet<>();
    private final StringBuilder out = new StringBuilder();

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File file = args.length > 0 ? new File(args[0]) : askFile("Write direct cvar JSON", "Export");
        DecompInterface decompiler = new DecompInterface();
        DecompileOptions options = new DecompileOptions();
        options.grabFromProgram(currentProgram);  // folds PIC string loads into literals
        decompiler.setOptions(options);
        decompiler.openProgram(currentProgram);

        Set<Function> functions = new LinkedHashSet<>();
        for (long target : new long[] {G_CONSOLE, CVAR_GET_INT_OR}) {
            for (Reference ref : getReferencesTo(toAddr(target))) {
                Function f = getFunctionContaining(ref.getFromAddress());
                if (f != null) {
                    functions.add(f);
                }
            }
        }
        for (Function f : functions) {
            DecompileResults result = decompiler.decompileFunction(f, 30, monitor);
            if (!result.decompileCompleted()) {
                continue;
            }
            String c = result.getDecompiledFunction().getC();
            Matcher m = REGISTER.matcher(c);
            while (m.find()) {
                add(m.group(1), m.group(2), "registered", f);
            }
            m = LOOKUP.matcher(c);
            while (m.find()) {
                add(m.group(1), null, "lookup", f);
            }
        }
        Files.writeString(file.toPath(), "[" + out + "]");
        println("ExportBozDirectCvars: " + functions.size() + " functions, " + seen.size() + " entries -> " + file);
    }

    private void add(String name, String def, String kind, Function f) {
        if (!seen.add(kind + ":" + name)) {
            return;
        }
        if (out.length() > 0) {
            out.append(',');
        }
        out.append("{\"name\":\"").append(name).append("\",\"kind\":\"").append(kind).append('"');
        if (def != null) {
            out.append(",\"default\":\"").append(def.replace("\\", "\\\\").replace("\"", "\\\"")).append('"');
        }
        out.append(",\"registered_in\":\"").append(f.getName(true)).append("\"}");
    }
}
