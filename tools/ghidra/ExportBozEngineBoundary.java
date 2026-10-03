// Maps the engine boundary: for each family of S3E/GL imports (s3eFile, s3eSound, gl, ...), which
// game functions call them directly, ranked by how many distinct imports of the family each uses.
// Functions that use many imports of one family are that subsystem's wrappers and managers.
//
// Calls reach imports through small thunks; both direct calls and calls through a thunk count.
// Output: JSON report to the given path.
// @category BOZ
// @menupath Tools.BOZ.Export Engine Boundary

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.io.FileWriter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.TreeSet;

public class ExportBozEngineBoundary extends GhidraScript {
    // Longest prefix wins.
    private static final String[] FAMILIES = {
        "s3eFile", "s3eSound", "s3eAudio", "s3eKeyboard", "s3ePointer", "s3eTouchpad", "s3eAccelerometer",
        "s3eSocket", "s3eInet", "s3eTimer", "s3eDevice", "s3eMemory", "s3eMalloc", "s3eFree", "s3eRealloc",
        "s3eConfig", "s3eSurface", "s3eGL", "s3eExt", "s3eVideo", "s3eDebug", "s3eOS", "s3eThread",
        "s3eCompass", "s3eLocation", "s3eVibra", "s3eWeb", "s3eCamera", "s3eImage", "s3eCrypto",
        "egl", "gl", "s3e",
    };

    private static String family(String name) {
        String best = "other";
        int length = 0;
        for (String prefix : FAMILIES) {
            if (name.startsWith(prefix) && prefix.length() > length) {
                best = prefix;
                length = prefix.length();
            }
        }
        return best;
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File out = args.length > 0 ? new File(args[0]) : askFile("Write engine boundary JSON", "Export");
        MemoryBlock imports = currentProgram.getMemory().getBlock(".imports");

        // Each import stub, plus any thunk functions that forward to it.
        Map<Address, String> targets = new HashMap<>();
        for (Function f : currentProgram.getFunctionManager().getFunctions(imports.getStart(), true)) {
            if (!imports.contains(f.getEntryPoint())) {
                break;
            }
            targets.put(f.getEntryPoint(), f.getName());
        }
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            Function thunked = f.isThunk() ? f.getThunkedFunction(true) : null;
            if (thunked != null && imports.contains(thunked.getEntryPoint())) {
                targets.put(f.getEntryPoint(), thunked.getName());
            }
        }

        // family -> caller -> imports used
        Map<String, Map<Function, TreeSet<String>>> byFamily = new TreeMap<>();
        Map<String, Integer> importCallers = new TreeMap<>();
        for (Map.Entry<Address, String> target : targets.entrySet()) {
            for (Reference ref : getReferencesTo(target.getKey())) {
                if (!ref.getReferenceType().isCall()) {
                    continue;
                }
                Function caller = getFunctionContaining(ref.getFromAddress());
                if (caller == null || imports.contains(caller.getEntryPoint()) || caller.isThunk()) {
                    continue;
                }
                String name = target.getValue();
                byFamily.computeIfAbsent(family(name), k -> new HashMap<>())
                        .computeIfAbsent(caller, k -> new TreeSet<>()).add(name);
                importCallers.merge(name, 1, Integer::sum);
            }
        }

        JsonObject report = new JsonObject();
        JsonArray families = new JsonArray();
        for (Map.Entry<String, Map<Function, TreeSet<String>>> entry : byFamily.entrySet()) {
            List<Map.Entry<Function, TreeSet<String>>> callers = new ArrayList<>(entry.getValue().entrySet());
            callers.sort((a, b) -> b.getValue().size() - a.getValue().size());
            TreeSet<String> used = new TreeSet<>();
            for (Map.Entry<Function, TreeSet<String>> c : callers) {
                used.addAll(c.getValue());
            }
            JsonObject family = new JsonObject();
            family.addProperty("family", entry.getKey());
            family.addProperty("imports_used", used.size());
            family.addProperty("callers", callers.size());
            JsonArray top = new JsonArray();
            for (Map.Entry<Function, TreeSet<String>> c : callers.subList(0, Math.min(25, callers.size()))) {
                JsonObject item = new JsonObject();
                item.addProperty("function", c.getKey().getName(true));
                item.addProperty("address", c.getKey().getEntryPoint().toString());
                item.addProperty("size", c.getKey().getBody().getNumAddresses());
                JsonArray names = new JsonArray();
                for (String n : c.getValue()) {
                    names.add(n);
                }
                item.add("imports", names);
                top.add(item);
            }
            family.add("top_callers", top);
            families.add(family);
        }
        report.add("families", families);
        JsonObject counts = new JsonObject();
        for (Map.Entry<String, Integer> e : importCallers.entrySet()) {
            counts.addProperty(e.getKey(), e.getValue());
        }
        report.add("call_sites_per_import", counts);
        report.addProperty("imports_never_called", targets.values().stream().distinct()
                .filter(n -> !importCallers.containsKey(n)).count());
        try (FileWriter writer = new FileWriter(out)) {
            new GsonBuilder().setPrettyPrinting().create().toJson(report, writer);
        }
        println(String.format("ExportBozEngineBoundary: %d families, %d imports called -> %s",
                byFamily.size(), importCallers.size(), out));
    }
}
