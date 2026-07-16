#!/usr/bin/env node
/** Runtime coverage for Pi's installed keybinding manager. */
import assert from "node:assert/strict";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [agentDir, packageDir] = process.argv.slice(2);

if (!agentDir || !packageDir) {
	throw new Error("Usage: keybindings_runtime_harness.mjs <agent-dir> <pi-package-dir>");
}

const keybindingsPath = resolve(packageDir, "dist", "core", "keybindings.js");
const { KeybindingsManager } = await import(pathToFileURL(keybindingsPath).href);
const keybindings = KeybindingsManager.create(resolve(agentDir));

assert.deepEqual(keybindings.getKeys("app.interrupt"), ["escape", "ctrl+["]);
assert.deepEqual(keybindings.getKeys("tui.select.cancel"), ["escape", "ctrl+c", "ctrl+["]);

for (const keybinding of ["app.interrupt", "tui.select.cancel"]) {
	assert.equal(keybindings.matches("\x1b", keybinding), true, `${keybinding} matches raw Escape`);
	assert.equal(keybindings.matches("\x1b[91;5u", keybinding), true, `${keybinding} matches CSI-u Ctrl+[`);
}

assert.equal(keybindings.matches("\x03", "tui.select.cancel"), true, "selector cancel matches Ctrl+C");
assert.equal(keybindings.matches("\x03", "app.interrupt"), false, "interrupt does not claim Ctrl+C");

console.log("Pi keybindings runtime harness: ok");
