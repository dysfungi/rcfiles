#!/usr/bin/env node
/** Unit coverage for MCP gateway precedence and mutation-verb tokenization. */
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const [policyPath] = process.argv.slice(2);
if (!policyPath) throw new Error("Usage: mcp_mutation_policy_harness.mjs <policy-path>");

const { checkMcpCall, checkMcpDirectToolCall } = await import(pathToFileURL(policyPath).href);

assert.equal(checkMcpCall({ tool: "getProjectSettings" }), null);
assert.match(checkMcpCall({ tool: "updateJiraIssue" }) ?? "", /mutating verb update/);
assert.equal(checkMcpCall({ action: "auth-start", tool: "updateJiraIssue" }), null);
assert.equal(checkMcpCall({ connect: "atlassian-rovo", tool: "updateJiraIssue" }), null);
assert.equal(checkMcpCall({ describe: "getJiraIssue", tool: "updateJiraIssue" }), null);
assert.equal(checkMcpCall({ search: "Jira", tool: "updateJiraIssue" }), null);
assert.equal(checkMcpCall({ server: "atlassian-rovo", tool: "updateJiraIssue" }), null);
assert.match(checkMcpDirectToolCall("atlassian_rovo_updateJiraIssue") ?? "", /mutating verb update/);
assert.equal(checkMcpDirectToolCall("atlassian_rovo_getProjectSettings"), null);

console.log("mcp mutation policy harness: ok");
